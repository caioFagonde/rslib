"""Durable local optical jobs, pinned inventories and a bounded ASGI worker.

SQLite is the queue and journal. A process-scoped flock elects one worker owner
per data directory; OS process death releases it. Raster operations cooperate at
scene/export checkpoints, rather than pretending that a GDAL read is interruptible.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rslib.cache import ResponseCache
from rslib.projects import ProjectConflict, Projects
from rslib.spectral_request import SpectralRequest, pin_request
from rslib.workflows import StackRequest, prepare_optical

TERMINAL = {"succeeded", "failed", "cancelled"}


class JobSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["optical", "spectral"] = "optical"
    spectral: SpectralRequest | None = None
    recipe: StackRequest | None = None
    project_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    revision: int | None = Field(default=None, ge=1)
    request_key: str | None = Field(default=None, pattern=r"^[a-f0-9-]{32,36}$")

    @model_validator(mode="after")
    def one_recipe(self):
        if self.kind == "spectral":
            if (
                self.spectral is None
                or self.recipe is not None
                or self.project_id is not None
                or self.revision is not None
            ):
                raise ValueError(
                    "A spectral job requires spectral parameters and no optical recipe/project override"
                )
            return self
        if self.spectral is not None:
            raise ValueError("Spectral parameters require kind=spectral")
        if self.project_id:
            if self.recipe is not None or self.revision is None:
                raise ValueError("A saved project job requires its revision and no recipe override")
        elif self.recipe is None or self.revision is not None:
            raise ValueError("Provide a recipe or a saved project and revision")
        return self


class JobConflict(ValueError):
    pass


class JobCancelled(Exception):
    pass


class WorkerStopping(Exception):
    pass


def now():
    return datetime.now(UTC).isoformat()


class Jobs(Projects):
    def __init__(self, path: Path):
        super().__init__(path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE, submission TEXT NOT NULL,
                    recipe TEXT NOT NULL, project_id TEXT REFERENCES projects(id),
                    recipe_revision INTEGER, status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL,
                    updated TEXT NOT NULL, inventory TEXT, progress TEXT NOT NULL,
                    error TEXT, run_id TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS job_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id), attempt INTEGER NOT NULL,
                    created TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS job_event_order ON job_events(job_id, sequence);
                CREATE INDEX IF NOT EXISTS job_queue ON jobs(status, created);
            """)
            db.execute("BEGIN IMMEDIATE")
            if "kind" not in {r["name"] for r in db.execute("PRAGMA table_info(jobs)")}:
                db.execute("ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'optical'")

    def result_path(self, job):
        return (
            self.path.parent
            / ("analyses" if job["kind"] == "spectral" else "runs")
            / job["run_id"]
            / ("report.json" if job["kind"] == "spectral" else "manifest.json")
        )

    @staticmethod
    def _event(db, identifier, phase, message, **details):
        payload = {"phase": phase, "message": message, **details}
        timestamp = now()
        db.execute(
            "UPDATE jobs SET updated=?,progress=? WHERE id=?",
            (timestamp, json.dumps(payload, allow_nan=False), identifier),
        )
        db.execute(
            "INSERT INTO job_events(job_id,attempt,created,payload) SELECT id,attempt,?,? FROM jobs WHERE id=?",
            (timestamp, json.dumps(payload, allow_nan=False), identifier),
        )

    def submit(self, spec: JobSpec):
        submission = spec.model_dump_json(exclude={"request_key"})
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id,submission FROM jobs WHERE request_key=?", (spec.request_key,)
            ).fetchone()
            if existing:
                # Normalize defaults for requests saved before the kind migration.
                previous = JobSpec.model_validate_json(existing["submission"])
                if previous.model_dump(exclude={"request_key"}) != spec.model_dump(
                    exclude={"request_key"}
                ):
                    raise JobConflict("Request key already belongs to a different submission")
                identifier = existing["id"]
            else:
                if (
                    db.execute(
                        "SELECT count(*) FROM jobs WHERE status IN ('queued','running','cancelling')"
                    ).fetchone()[0]
                    >= 32
                ):
                    raise JobConflict("The local queue is full (32 active jobs)")
                recipe = (
                    pin_request(self.path.parent, spec.spectral)
                    if spec.kind == "spectral"
                    else spec.recipe
                )
                if spec.project_id:
                    project = db.execute(
                        "SELECT recipe,revision FROM projects WHERE id=?", (spec.project_id,)
                    ).fetchone()
                    if project is None:
                        raise KeyError("Project not found")
                    if project["revision"] != spec.revision:
                        raise ProjectConflict(
                            "Project changed before submission. Reload it before running."
                        )
                    recipe = StackRequest.model_validate_json(project["recipe"])
                identifier, timestamp = uuid.uuid4().hex, now()
                db.execute(
                    """INSERT INTO jobs(id,request_key,submission,recipe,project_id,recipe_revision,
                           status,created,updated,progress,run_id,kind) VALUES(?,?,?,?,?,?,'queued',?,?,'{}',?,?)""",
                    (
                        identifier,
                        spec.request_key,
                        submission,
                        recipe.model_dump_json(),
                        spec.project_id,
                        spec.revision,
                        timestamp,
                        timestamp,
                        uuid.uuid4().hex,
                        spec.kind,
                    ),
                )
                self._event(db, identifier, "queued", "Waiting for a processing slot")
        return self.get_job(identifier)

    def get_job(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise KeyError("Job not found")
        return {
            k: row[k]
            for k in [
                "id",
                "kind",
                "project_id",
                "recipe_revision",
                "status",
                "attempt",
                "created",
                "updated",
                "run_id",
            ]
        } | {
            "recipe": json.loads(row["recipe"]),
            "cancel_requested": bool(row["cancel_requested"]),
            "progress": json.loads(row["progress"]),
            "inventory_count": len(json.loads(row["inventory"])["observations"])
            if row["inventory"]
            else 0,
            "error": json.loads(row["error"]) if row["error"] else None,
            "manifest_url": (
                f"/api/analyses/{row['run_id']}/report.json"
                if row["kind"] == "spectral"
                else f"/api/runs/{row['run_id']}/manifest.json"
            )
            if row["status"] == "succeeded"
            else None,
        }

    def list_jobs(self, project_id=None, source_run_id=None):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id FROM jobs WHERE (? IS NULL OR project_id=?) AND (? IS NULL OR (kind='spectral' AND json_extract(recipe,'$.run_id')=?)) ORDER BY created DESC LIMIT 50",
                (project_id, project_id, source_run_id, source_run_id),
            ).fetchall()
        return [self.get_job(row["id"]) for row in rows]

    def events(self, identifier, after=0):
        self.get_job(identifier)
        with self.connect() as db:
            rows = db.execute(
                "SELECT sequence,attempt,created,payload FROM job_events WHERE job_id=? AND sequence>? ORDER BY sequence LIMIT 200",
                (identifier, after),
            ).fetchall()
        return [
            {
                "sequence": r["sequence"],
                "attempt": r["attempt"],
                "created": r["created"],
                **json.loads(r["payload"]),
            }
            for r in rows
        ]

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id FROM jobs WHERE status='queued' ORDER BY created,id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            identifier = row["id"]
            db.execute(
                "UPDATE jobs SET status='running',attempt=attempt+1,error=NULL WHERE id=?",
                (identifier,),
            )
            self._event(db, identifier, "starting", "Starting saved recipe")
        return self.get_job(identifier)

    def inventory(self, identifier):
        with self.connect() as db:
            value = db.execute("SELECT inventory FROM jobs WHERE id=?", (identifier,)).fetchone()[0]
        return json.loads(value) if value else None

    def checkpoint(self, identifier, event):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT cancel_requested,status FROM jobs WHERE id=?", (identifier,)
            ).fetchone()
            if row["cancel_requested"]:
                raise JobCancelled()
            if row["status"] != "running":
                raise WorkerStopping()
            event = dict(event)
            inventory = event.pop("inventory", None)
            if inventory:
                db.execute(
                    "UPDATE jobs SET inventory=coalesce(inventory,?) WHERE id=?",
                    (json.dumps(inventory, allow_nan=False), identifier),
                )
            self._event(db, identifier, **event)

    def cancel(self, identifier):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM jobs WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError("Job not found")
            if row["status"] not in TERMINAL:
                queued = row["status"] == "queued"
                status = "cancelled" if queued else "cancelling"
                db.execute(
                    "UPDATE jobs SET cancel_requested=1,status=? WHERE id=?", (status, identifier)
                )
                self._event(
                    db,
                    identifier,
                    status,
                    "Cancelled before execution"
                    if queued
                    else "Cancellation requested; waiting for the current processing checkpoint",
                )
        return self.get_job(identifier)

    def retry(self, identifier):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,kind FROM jobs WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError("Job not found")
            if row["status"] not in {"failed", "cancelled"}:
                raise JobConflict("Only failed or cancelled jobs can be retried")
            if (
                db.execute(
                    "SELECT count(*) FROM jobs WHERE status IN ('queued','running','cancelling')"
                ).fetchone()[0]
                >= 32
            ):
                raise JobConflict("The local queue is full (32 active jobs)")
            db.execute(
                "UPDATE jobs SET status='queued',cancel_requested=0,error=NULL WHERE id=?",
                (identifier,),
            )
            self._event(
                db,
                identifier,
                "queued",
                "Retry queued with the saved fit and pinned input checksums"
                if row["kind"] == "spectral"
                else "Retry queued with the saved recipe and scene inventory",
            )
        return self.get_job(identifier)

    def recover(self):
        """Only the process holding the data-directory worker lock may call this."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT id,kind,run_id,cancel_requested FROM jobs WHERE status IN ('running','cancelling')"
            ).fetchall()
            for row in rows:
                published = self.result_path(row).exists()
                cancelled = row["cancel_requested"] and not published
                status = "cancelled" if cancelled else "queued"
                db.execute(
                    "UPDATE jobs SET status=?,cancel_requested=? WHERE id=?",
                    (status, int(cancelled), row["id"]),
                )
                self._event(
                    db,
                    row["id"],
                    "recovered",
                    "Published exports found after interruption; reconciling job state"
                    if published
                    else "Recovered interrupted attempt; cancellation retained"
                    if cancelled
                    else "Recovered interrupted spectral fit; restarting on the pinned optical input"
                    if row["kind"] == "spectral"
                    else "Recovered interrupted attempt; reusing saved inventory and scene cache",
                )

    def finish(self, identifier, *, report=None, status="succeeded", error=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if report:
                row = db.execute(
                    "SELECT project_id,recipe_revision FROM jobs WHERE id=?", (identifier,)
                ).fetchone()
                if row["project_id"]:
                    summary = {k: report[k] for k in ["summary", "synthetic", "timings"]}
                    db.execute(
                        "INSERT OR IGNORE INTO project_runs VALUES(?,?,?,?,?)",
                        (
                            row["project_id"],
                            report["id"],
                            row["recipe_revision"],
                            now(),
                            json.dumps(summary, allow_nan=False),
                        ),
                    )
                    db.execute(
                        "UPDATE projects SET updated=? WHERE id=?", (now(), row["project_id"])
                    )
            db.execute(
                "UPDATE jobs SET status=?,error=? WHERE id=?",
                (status, json.dumps(error) if error else None, identifier),
            )
            self._event(
                db,
                identifier,
                status,
                "Complete exports are available"
                if report
                else (error or {}).get("message", "Cancelled at a processing checkpoint"),
            )


class JobRunner:
    def __init__(self, data: Path, store: Jobs, slots: asyncio.Semaphore, cache: ResponseCache):
        self.data, self.store, self.slots, self.cache = data, store, slots, cache
        self.stopping = threading.Event()
        self.tasks = []
        self.lock = None

    async def start(self, *, require_owner: bool = True):
        self.lock = (self.data / "worker.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            self.lock = None
            if require_owner:
                raise RuntimeError(
                    "Another RSLIB server owns this data directory. Use one server process per directory."
                ) from None
            return False
        await asyncio.to_thread(self.store.recover)
        self.tasks = [asyncio.create_task(self.work()) for _ in range(2)]
        return True

    async def stop(self):
        self.stopping.set()
        try:
            await asyncio.gather(*self.tasks)
        finally:
            if self.lock:
                fcntl.flock(self.lock, fcntl.LOCK_UN)
                self.lock.close()
                self.lock = None

    async def work(self):
        while not self.stopping.is_set():
            async with self.slots:
                if self.stopping.is_set():
                    break
                job = await asyncio.to_thread(self.store.claim)
                if job:
                    await self.execute(job)
            if not job:
                await asyncio.sleep(0.15)

    async def execute(self, job):
        identifier = job["id"]

        def progress(event):
            if self.stopping.is_set():
                raise WorkerStopping()
            self.store.checkpoint(identifier, event)

        try:
            # A crash after atomic publication but before the SQLite commit must
            # attach the existing immutable result, rather than recompute it.
            manifest = self.store.result_path(job)
            if manifest.exists():
                if job["kind"] == "spectral":
                    from rslib.spectral_workflow import load_spectral_report

                    report = await asyncio.to_thread(
                        load_spectral_report, manifest.parent, expected_recipe=job["recipe"]
                    )
                else:
                    report = json.loads(manifest.read_text())
            elif job["kind"] == "spectral":
                from rslib.spectral_workflow import analyze_spectra

                spec = SpectralRequest(**job["recipe"])
                report = await asyncio.to_thread(
                    analyze_spectra,
                    self.data / "runs" / spec.run_id,
                    manifest.parent,
                    source_index=spec.source_index,
                    endmembers=spec.endmembers,
                    seed=spec.seed,
                    components=spec.components,
                    projection=spec.projection,
                    expected_checksums=spec.input_checksums,
                    progress=progress,
                    resume=job["attempt"] > 1,
                )
            else:
                report = await prepare_optical(
                    StackRequest(**job["recipe"]),
                    self.data,
                    catalog_cache=self.cache,
                    progress=progress,
                    inventory=await asyncio.to_thread(self.store.inventory, identifier),
                    run_id=job["run_id"],
                    resume=job["attempt"] > 1,
                )
            await asyncio.to_thread(self.store.finish, identifier, report=report)
        except JobCancelled:
            await asyncio.to_thread(self.store.finish, identifier, status="cancelled")
        except WorkerStopping:
            # Recovery requeues this attempt after the next exclusive startup.
            pass
        except Exception as exc:
            message = (
                str(exc)
                if isinstance(exc, ValueError)
                else "Source or spectral processing failure. Retry retains the pinned input run."
                if job["kind"] == "spectral"
                else "Source or processing failure. Retry reuses completed scene work."
            )
            await asyncio.to_thread(
                self.store.finish,
                identifier,
                status="failed",
                error={"code": type(exc).__name__, "message": message},
            )
