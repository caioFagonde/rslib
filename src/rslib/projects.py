"""Local project specifications and immutable run references in SQLite."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from rslib.workflows import StackRequest


class ProjectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    recipe: StackRequest


class ProjectUpdate(ProjectSpec):
    revision: int = Field(ge=1)


class ProjectRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


class ProjectConflict(ValueError):
    pass


class Projects:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, recipe TEXT NOT NULL,
                    revision INTEGER NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_runs (
                    project_id TEXT NOT NULL REFERENCES projects(id), run_id TEXT NOT NULL UNIQUE,
                    recipe_revision INTEGER NOT NULL, created TEXT NOT NULL, summary TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS project_run_order ON project_runs(project_id, created DESC);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, spec: ProjectSpec) -> dict:
        identifier, now = uuid.uuid4().hex, datetime.now(UTC).isoformat()
        with self.connect() as db:
            db.execute(
                "INSERT INTO projects VALUES (?,?,?,?,?,?)",
                (
                    identifier,
                    spec.name,
                    spec.recipe.model_dump_json(),
                    1,
                    now,
                    now,
                ),
            )
        return self.get(identifier)

    def list(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,name,revision,created,updated,recipe FROM projects ORDER BY updated DESC LIMIT 100"
            ).fetchall()
        return [
            {k: row[k] for k in ["id", "name", "revision", "created", "updated"]}
            | {"field_count": len(json.loads(row["recipe"]).get("fields", []))}
            for row in rows
        ]

    def get(self, identifier: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM projects WHERE id=?", (identifier,)).fetchone()
            runs = db.execute(
                "SELECT run_id,recipe_revision,created,summary FROM project_runs WHERE project_id=? ORDER BY created DESC LIMIT 50",
                (identifier,),
            ).fetchall()
        if row is None:
            raise KeyError("Project not found")
        return {
            "id": row["id"],
            "name": row["name"],
            "revision": row["revision"],
            "created": row["created"],
            "updated": row["updated"],
            "recipe": json.loads(row["recipe"]),
            "runs": [
                {
                    "id": r["run_id"],
                    "recipe_revision": r["recipe_revision"],
                    "created": r["created"],
                    **json.loads(r["summary"]),
                }
                for r in runs
            ],
        }

    def update(self, identifier: str, spec: ProjectUpdate) -> dict:
        with self.connect() as db:
            changed = db.execute(
                "UPDATE projects SET name=?,recipe=?,revision=revision+1,updated=? WHERE id=? AND revision=?",
                (
                    spec.name,
                    spec.recipe.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                    identifier,
                    spec.revision,
                ),
            ).rowcount
            if not changed:
                if (
                    db.execute("SELECT 1 FROM projects WHERE id=?", (identifier,)).fetchone()
                    is None
                ):
                    raise KeyError("Project not found")
                raise ProjectConflict(
                    "Project changed in another session. Reload it before saving."
                )
        return self.get(identifier)

    def attach(self, identifier: str, revision: int, report: dict) -> None:
        summary = {k: report[k] for k in ["summary", "synthetic", "timings"]}
        with self.connect() as db:
            now = datetime.now(UTC).isoformat()
            db.execute(
                "INSERT INTO project_runs VALUES (?,?,?,?,?)",
                (identifier, report["id"], revision, now, json.dumps(summary, allow_nan=False)),
            )
            db.execute("UPDATE projects SET updated=? WHERE id=?", (now, identifier))
