from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image
from rich.color import Color
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from rslib.cache import ResponseCache
from rslib.demo import create_demo
from rslib.models import AnalysisRequest, BBox, Search
from rslib.pipeline import analyze_scene
from rslib.stac import client_for


class RasterView(Static):
    """Universal RGB half-block rendering over SSH; no terminal-specific escape sequences."""

    image: Image.Image | None = None

    def set_image(self, path: Path):
        with Image.open(path) as src:
            self.image = src.convert("RGBA")
        self.refresh()

    def on_resize(self):
        self.refresh()

    def render(self) -> Text:
        if self.image is None:
            return Text(
                "\n  RSLIB / EARTH OBSERVATION\n\n  d  Load synthetic scenes\n  s  Search STAC\n  a  Analyze selected scene\n  w  Prepare optical stack + time series\n\n  Raster imagery renders here as true-color half blocks.",
                style="#bce8a5",
            )
        width, height = min(140, max(1, self.size.width)), min(70, max(1, self.size.height))
        image = self.image.copy()
        image.thumbnail((width, height * 2))
        text = Text()
        for y in range(0, image.height, 2):
            for x in range(image.width):
                top, bottom = (
                    image.getpixel((x, y)),
                    image.getpixel((x, min(y + 1, image.height - 1))),
                )
                fg = Color.from_rgb(*top[:3]) if top[3] else Color.from_rgb(20, 35, 26)
                bg = Color.from_rgb(*bottom[:3]) if bottom[3] else Color.from_rgb(20, 35, 26)
                text.append("▀", style=Style(color=fg, bgcolor=bg))
            if y + 2 < image.height:
                text.append("\n")
        return text


class Workbench(App):
    TITLE = "RSLIB / Earth observation workbench"
    CSS = """
    Screen {background: #101e17; color: #c6dfbc;}
    Header {background: #21382a;}
    #workspace {height: 1fr;}
    #controls {width: 31; padding: 1; border-right: solid #496340;}
    #viewer {width: 1fr; padding: 1;}
    #observations {width: 38; border-left: solid #496340; padding: 1;}
    #raster {height: 1fr; min-height: 12; background: #14231a;}
    Input, Select {margin: 0 0 1 0;}
    Label {color: #99b48f; margin-top: 1;}
    Button {width: 100%; margin-bottom: 1;}
    #scene-table {height: 15;}
    #area-table {height: 7;}
    #area-history-table {height: 1fr;}
    #diagnostics-table {height: 1fr;}
    #diagnostics-summary {height: auto; padding: 1;}
    #diagnostics-buttons {height: 3;}
    #diagnostics-buttons Button {width: 1fr;}
    #jobs-table {height: 9;}
    .spectral-row {height: 4;}
    .spectral-row Input, .spectral-row Select, .spectral-row Button {width: 1fr;}
    #spectral-result {height: 34;}
    #spectral-raster {width: 1fr; height: 31;}
    #spectral-tables {width: 1fr;}
    #spectral-values, #spectral-members, #spectral-loadings {height: 8;}
    #spectral-summary, #spectral-exports {height: auto; padding: 1;}

    #job-journal {height: auto; padding: 1;}
    #job-buttons {height: 3;}
    #job-buttons Button {width: 1fr;}
    #status {height: auto; min-height: 2; padding: 1; background: #21382a;}
    #summary {height: auto; padding: 1;}
    TabbedContent {height: 1fr;}
    #hydro-text, #provenance, #help-text {height: auto; padding: 1;}
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("d", "demo", "Demo"),
        ("s", "search", "Search"),
        ("a", "analyze", "Analyze"),
        ("h", "hydro", "Rust hydro"),
        ("w", "stack", "Optical stack"),
        ("[", "previous_frame", "Prev date"),
        ("]", "next_frame", "Next date"),
        ("g", "support", "Gap support"),
        ("f", "fields", "Area statistics"),
        ("j", "jobs", "Jobs"),
        ("x", "spectral", "Spectral analysis"),
    ]

    def __init__(self, data_dir: Path, project_id: str | None = None):
        super().__init__()
        self.data_dir = data_dir.resolve()
        self.cache = ResponseCache(self.data_dir / "cache" / "stac.sqlite3")
        self.scenes: list[dict] = []
        self.active_provider = "demo"
        self.selected = 0
        self.active_bbox = BBox(west=-44.75, south=-22.5, east=-44.55, north=-22.3)
        self.working = False
        self.diagnostics_busy = False
        self.last_stack: dict | None = None
        self.stack_frame = 0
        self.stack_support = False
        from rslib.projects import Projects

        self.projects = Projects(self.data_dir / "projects.sqlite3")
        self.project = self.projects.get(project_id) if project_id else None
        from rslib.jobs import JobRunner, Jobs

        self.jobs = Jobs(self.data_dir / "projects.sqlite3")
        self.job_runner = JobRunner(self.data_dir, self.jobs, asyncio.Semaphore(2), self.cache)
        self.selected_job_id: str | None = None
        self.spectral_report: dict | None = None
        self.spectral_busy = False
        self.spectral_input: dict | None = None
        self.spectral_cell: dict | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="workspace"):
            with VerticalScroll(id="controls"):
                yield Static("◈  DISCOVER / ANALYZE")
                yield Label("Data connection")
                yield Select(
                    [
                        ("Synthetic demo", "demo"),
                        ("Earth Search / AWS", "earth-search"),
                        ("Planetary Computer", "planetary-computer"),
                    ],
                    value="demo",
                    allow_blank=False,
                    id="provider",
                )
                yield Label("Collection")
                yield Input("sentinel-2-c1-l2a", id="collection")
                yield Label("AOI / W,S,E,N")
                yield Input("-44.75,-22.5,-44.55,-22.3", id="bbox")
                yield Label("ISO date interval (blank for DEM)")
                yield Input("2026-06-01/2026-08-01", id="dates")
                yield Label("Max cloud % (blank = no filter)")
                yield Input("30", id="cloud")
                yield Button("Search catalog [s]", id="search")
                yield Label("Analysis")
                yield Select(
                    [(v.upper(), v) for v in ("ndvi", "ndmi", "nbr", "evi", "rgb")],
                    value="ndvi",
                    allow_blank=False,
                    id="index",
                )
                yield Button("Analyze scene [a]", id="analyze", variant="success")
                yield Label("Optical stack / Sentinel-2 + Landsat")
                yield Label("Regular interval / days")
                yield Input("5", id="stack-step", placeholder="Regular step / days")
                yield Label("Maximum bracket / days")
                yield Input("20", id="stack-gap", placeholder="Maximum bracket / days")
                yield Button("Prepare optical stack [w]", id="stack")
                yield Button("Synthetic fixture [d]", id="demo")
                yield Button("Rust storm model [h]", id="hydro")
            with Vertical(id="viewer"):
                with TabbedContent(id="tabs"):
                    with TabPane("Raster", id="raster-tab"):
                        yield RasterView(id="raster")
                    with TabPane("Provenance", id="report-tab"):
                        with VerticalScroll():
                            yield Static(
                                "Run an analysis to inspect provenance.",
                                id="provenance",
                                markup=False,
                            )
                    with TabPane("Monitoring areas", id="areas-tab"):
                        yield Static(
                            "Prepare a project with polygon areas.", id="areas-date", markup=False
                        )
                        yield DataTable(id="area-table", cursor_type="row")
                        yield DataTable(id="area-history-table", cursor_type="row")
                        yield Static("", id="areas-note", markup=False)
                    with TabPane("Jobs", id="jobs-tab"):
                        yield DataTable(id="jobs-table", cursor_type="row")
                        with Horizontal(id="job-buttons"):
                            yield Button("Cancel selected job", id="cancel-job")
                            yield Button("Retry saved job", id="retry-job")
                            yield Button("Open result", id="open-job")
                        with VerticalScroll():
                            yield Static("No job selected.", id="job-journal", markup=False)
                    with TabPane("Spectral analysis", id="spectral-tab"):
                        with VerticalScroll():
                            yield Label("Optical run ID · PCA components / endmembers / seed")
                            with Horizontal(classes="spectral-row"):
                                yield Input(placeholder="Completed optical run ID", id="sp-run-id")
                                yield Button("Load source inventory", id="sp-load")
                            yield Select(
                                [("Load an optical run", "")],
                                value="",
                                allow_blank=False,
                                id="sp-source",
                            )
                            with Horizontal(classes="spectral-row"):
                                yield Input(
                                    value="3",
                                    placeholder="PCA components",
                                    id="sp-components",
                                    type="integer",
                                )
                                yield Input(
                                    value="3",
                                    placeholder="Endmembers",
                                    id="sp-endmembers",
                                    type="integer",
                                )
                                yield Input(
                                    value="0",
                                    placeholder="Random seed",
                                    id="sp-seed",
                                    type="integer",
                                )
                                yield Select(
                                    [("Affine VCA", "affine"), ("Projective VCA", "projective")],
                                    value="affine",
                                    allow_blank=False,
                                    id="sp-projection",
                                )
                            with Horizontal(classes="spectral-row"):
                                yield Button("Run spectral job", id="sp-run", disabled=True)
                                yield Select(
                                    [("No analysis", "")], value="", allow_blank=False, id="sp-map"
                                )
                            yield Static(
                                "Open a run or press x after loading an optical project.",
                                id="spectral-summary",
                                markup=False,
                            )
                            with Horizontal(id="spectral-result"):
                                yield RasterView(id="spectral-raster")
                                with Vertical(id="spectral-tables"):
                                    yield Static("Cell spectrum: reflectance (1)")
                                    yield DataTable(id="spectral-values")
                                    yield Static("Endmember sources and cell fractions")
                                    yield DataTable(id="spectral-members", cursor_type="row")
                                    yield Select(
                                        [("No PCA component", "0")],
                                        value="0",
                                        allow_blank=False,
                                        id="sp-loading",
                                    )
                                    yield Static("", id="sp-variance", markup=False)
                                    yield DataTable(id="spectral-loadings")
                            with Horizontal(classes="spectral-row"):
                                yield Input(
                                    value="0", placeholder="Row", id="sp-row", type="integer"
                                )
                                yield Input(
                                    value="0", placeholder="Column", id="sp-col", type="integer"
                                )
                                yield Button("Inspect cell", id="sp-inspect")
                            yield Static(
                                "Artifacts and printable report appear here.",
                                id="spectral-exports",
                                markup=False,
                            )
                    with TabPane("Quantitative checks", id="diagnostics-tab"):
                        with Horizontal(id="diagnostics-buttons"):
                            yield Button("Compare sensors", id="compare-sensors")
                            yield Button("Withhold acquisition days", id="validate-series")
                        yield Static(
                            "Open or prepare an optical run first.",
                            id="diagnostics-summary",
                            markup=False,
                        )
                        yield DataTable(id="diagnostics-table", cursor_type="row")
                    with TabPane("Hydro", id="hydro-tab"):
                        with VerticalScroll():
                            yield Static(
                                "h: Run a hypothetical storm using our Rust wet-initial-condition solver.",
                                id="hydro-text",
                                markup=False,
                            )
                    with TabPane("Help", id="help-tab"):
                        yield Static(
                            "Live catalogs require networking. Demo and scientific calculations run offline.\n\nAll work happens in background workers. q quits; Tab changes focus.\n\nw prepares a common-grid Sentinel-2/Landsat stack and regular series. [ ] selects dates; g toggles observed/interpolated/missing support. The selected provider determines demo versus live mode; live stacks search both optical catalogs.\n\nCloud cover is scene-wide; native QA masks filter stack pixels before averaging. Artifacts are written under data/runs.\n\nd uses repeated synthetic dates; w uses a changing synthetic multi-sensor sequence. Both are labeled and are not satellite observations.",
                            id="help-text",
                        )
            with VerticalScroll(id="observations"):
                yield Static("OBSERVATION STACK")
                yield DataTable(id="scene-table", cursor_type="row")
                yield Static("Select a scene and run analysis.", id="summary", markup=False)
        yield Static(
            "Ready · synthetic data is labeled · no scene downloaded on startup",
            id="status",
            markup=False,
        )
        yield Footer()

    async def on_mount(self):
        self.query_one("#scene-table", DataTable).add_columns("Date", "Cloud %")
        self.query_one("#area-table", DataTable).add_columns(
            "Area", "ha", "Observed", "Estimated", "Missing", "Mean obs"
        )
        self.query_one("#area-history-table", DataTable).add_columns(
            "Date / UTC", "Area", "Observed", "Estimated", "Missing", "Mean obs", "Mean supported"
        )
        self.query_one("#jobs-table", DataTable).add_columns(
            "Job", "State", "Attempt", "Checkpoint"
        )
        self.query_one("#spectral-values", DataTable).add_columns(
            "Band", "Observed", "Reconstructed", "Residual"
        )
        self.query_one("#spectral-members", DataTable).add_columns(
            "Endmember", "Row, col", "Fraction"
        )
        self.query_one("#spectral-loadings", DataTable).add_columns("Band", "Loading")
        await self.job_runner.start(require_owner=False)
        self.refresh_jobs()
        self.set_interval(1, self.refresh_jobs)
        self.set_interval(2, self.ensure_job_worker)
        if self.project:
            import json

            r = self.project["recipe"]
            self.sub_title = self.project["name"]
            self.query_one("#provider", Select).value = "demo" if r["demo"] else "earth-search"
            self.query_one("#bbox", Input).value = ",".join(
                str(r["bbox"][key]) for key in ["west", "south", "east", "north"]
            )
            self.query_one("#dates", Input).value = r["datetime"]
            self.query_one("#index", Select).value = r["index"]
            self.query_one("#cloud", Input).value = str(r["max_cloud"])
            self.query_one("#stack-step", Input).value = str(r["step_days"])
            self.query_one("#stack-gap", Input).value = str(r["max_gap_days"])
            runs = self.project["runs"]
            if runs and runs[0]["recipe_revision"] == self.project["revision"]:
                path = self.data_dir / "runs" / runs[0]["id"] / "manifest.json"
                if path.is_file():
                    self.last_stack = json.loads(path.read_text())
                    self.query_one("#provenance", Static).update(
                        json.dumps(self.last_stack, indent=2)
                    )
                    self.show_stack_frame()

    async def on_unmount(self):
        await self.job_runner.stop()

    async def ensure_job_worker(self):
        if not self.is_running:
            return
        if not self.job_runner.lock and not self.job_runner.stopping.is_set():
            await self.job_runner.start(require_owner=False)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated):
        if event.tabbed_content.id == "tabs":
            # Discovery inputs are independent of a saved spectral source.
            # Give that task the full workspace instead of showing stale inputs.
            spectral = event.pane.id == "spectral-tab"
            # Tab events can finish dispatching while the screen unmounts.
            for identifier in ("controls", "observations"):
                for widget in self.query(f"#{identifier}"):
                    widget.display = not spectral

    def refresh_jobs(self):
        if not self.is_running:
            return
        jobs = self.jobs.list_jobs()
        table = self.query_one("#jobs-table", DataTable)
        table.clear()
        for job in jobs:
            table.add_row(
                job["id"][:8] + (" / spectra" if job["kind"] == "spectral" else " / optical"),
                job["status"],
                str(job["attempt"]),
                job["progress"].get("message", ""),
                key=job["id"],
            )
        selected = next((j for j in jobs if j["id"] == self.selected_job_id), None)
        if not selected and jobs:
            selected = jobs[0]
            self.selected_job_id = selected["id"]
        if selected:
            events = self.jobs.events(selected["id"])
            context = (
                f"Pinned optical run {selected['recipe']['run_id']} / source {selected['recipe']['source_index']}"
                if selected["kind"] == "spectral"
                else f"{selected['inventory_count']} saved candidates; recipe revision {selected['recipe_revision'] or 'unsaved'}"
            )
            text = f"{selected['id']} / {selected['status']} / attempt {selected['attempt']}\n{context}\n\n"
            text += "\n".join(
                f"{e['created'][11:19]} UTC / {e['attempt']} / {e['message']}" for e in events[-30:]
            )
            if selected["error"]:
                text += f"\n\n{selected['error']['code']}: {selected['error']['message']}"
            self.query_one("#job-journal", Static).update(text)
        self.query_one("#cancel-job", Button).disabled = not selected or selected["status"] not in {
            "queued",
            "running",
        }
        self.query_one("#retry-job", Button).disabled = not selected or selected["status"] not in {
            "failed",
            "cancelled",
        }
        self.query_one("#open-job", Button).disabled = (
            not selected or selected["status"] != "succeeded"
        )

    def open_selected_job(self):
        import json

        if not self.selected_job_id:
            return
        job = self.jobs.get_job(self.selected_job_id)
        if job["status"] != "succeeded":
            return
        if job["kind"] == "spectral":
            self.open_spectral_job(job)
            return
        self.last_stack = json.loads(
            (self.data_dir / "runs" / job["run_id"] / "manifest.json").read_text()
        )
        self.stack_frame, self.stack_support = 0, False
        self.query_one("#provenance", Static).update(json.dumps(self.last_stack, indent=2))
        self.show_stack_frame()

    def action_spectral(self):
        self.query_one("#tabs", TabbedContent).active = "spectral-tab"
        if self.last_stack:
            self.query_one("#sp-run-id", Input).value = self.last_stack["id"]
            self.load_spectral_sources()

    @work(group="spectral-inventory", exclusive=True)
    async def load_spectral_sources(self):
        import json
        import re

        try:
            identifier = self.query_one("#sp-run-id", Input).value
            if not re.fullmatch(r"[a-f0-9]{32}", identifier):
                raise ValueError("Enter a completed optical run ID")
            self.spectral_input = None
            self.query_one("#sp-run", Button).disabled = True
            report = await asyncio.to_thread(
                lambda: json.loads(
                    (self.data_dir / "runs" / identifier / "manifest.json").read_text()
                )
            )
            if report.get("schema_version") != "rslib-stack-workflow/1":
                raise ValueError("This is not an optical stack")
            self.spectral_input = report
            self.query_one("#sp-source", Select).set_options(
                [
                    (f"{s['datetime'][:10]} / {s['platform']} / {s['id']}", str(i))
                    for i, s in enumerate(report["observations"])
                ]
            )
            self.query_one("#sp-source", Select).value = "0"
            self.query_one("#sp-run", Button).disabled = False
            self.query_one("#spectral-summary", Static).update(
                f"{'SYNTHETIC' if report['synthetic'] else 'SATELLITE'} / {len(report['observations'])} source acquisitions. Fit uses complete observed spectra only."
            )
        except Exception as exc:
            self.set_status(f"Spectral input could not be loaded: {exc}")

    @work(group="spectral-job")
    async def run_spectral_job(self):
        if self.spectral_busy:
            return
        from rslib.jobs import JobSpec
        from rslib.spectral_request import SpectralRequest

        self.spectral_busy = True
        self.query_one("#sp-run", Button).disabled = True
        try:
            identifier = self.query_one("#sp-run-id", Input).value
            if not self.spectral_input or self.spectral_input["id"] != identifier:
                raise ValueError("Load the selected run's source inventory first")
            recipe = SpectralRequest(
                run_id=identifier,
                source_index=int(str(self.query_one("#sp-source", Select).value)),
                components=int(self.query_one("#sp-components", Input).value),
                endmembers=int(self.query_one("#sp-endmembers", Input).value),
                projection=str(self.query_one("#sp-projection", Select).value),
                seed=int(self.query_one("#sp-seed", Input).value),
            )
            job = await asyncio.to_thread(
                self.jobs.submit, JobSpec(kind="spectral", spectral=recipe)
            )
            self.selected_job_id = job["id"]
            self.action_jobs()
            while self.is_running:
                job = await asyncio.to_thread(self.jobs.get_job, job["id"])
                self.set_status(f"Spectral {job['status']}: {job['progress'].get('message', '')}")
                if job["status"] in {"succeeded", "failed", "cancelled"}:
                    break
                await asyncio.sleep(0.15)
            if job["status"] == "succeeded" and self.is_running:
                await self.display_spectral_job(job)
            elif self.is_running:
                self.set_status(
                    (job["error"] or {}).get(
                        "message", "Spectral job cancelled; the optical run is unchanged."
                    )
                )
        except Exception as exc:
            if self.is_running:
                self.set_status(f"Spectral job failed: {exc}")
        finally:
            self.spectral_busy = False
            if self.is_running:
                self.query_one("#sp-run", Button).disabled = self.spectral_input is None

    @work(group="spectral-open", exclusive=True)
    async def open_spectral_job(self, job):
        try:
            await self.display_spectral_job(job)
        except Exception as exc:
            self.set_status(f"Spectral result could not be opened: {exc}")

    async def display_spectral_job(self, job):
        import json

        from rslib.spectral_workflow import load_spectral_report

        report = await asyncio.to_thread(
            load_spectral_report, self.data_dir / "analyses" / job["run_id"]
        )
        self.spectral_report = report
        try:
            self.spectral_input = await asyncio.to_thread(
                lambda: json.loads(
                    (self.data_dir / "runs" / report["run_id"] / "manifest.json").read_text()
                )
            )
        except FileNotFoundError:
            self.spectral_input = None
        self.query_one("#sp-run-id", Input).value = report["run_id"]
        self.query_one("#sp-source", Select).set_options(
            [
                (f"{s['datetime'][:10]} / {s['id']}", str(i))
                for i, s in enumerate(self.spectral_input["observations"])
            ]
            if self.spectral_input
            else [(report["source"]["id"], str(report["source_index"]))]
        )
        self.query_one("#sp-source", Select).value = str(report["source_index"])
        for key in ["components", "endmembers", "seed"]:
            self.query_one(f"#sp-{key}", Input).value = str(report["recipe"][key])
        self.query_one("#sp-projection", Select).value = report["recipe"]["projection"]
        self.query_one("#sp-run", Button).disabled = self.spectral_input is None
        views = self.query_one("#sp-map", Select)
        views.set_options([(d["title"], d["filename"]) for d in report["displays"]])
        views.value = "abundance.png"
        self.query_one("#spectral-raster", RasterView).set_image(
            self.data_dir / "analyses" / report["id"] / "abundance.png"
        )
        self.spectral_cell = None
        self.query_one("#sp-loading", Select).set_options(
            [(f"PC{i + 1}", str(i)) for i in range(len(report["pca"]["loadings"]))]
        )
        self.query_one("#sp-loading", Select).value = "0"
        self.update_spectral_loadings()
        self.query_one(
            "#spectral-summary", Static
        ).update(f"""{"SYNTHETIC" if report["synthetic"] else "SATELLITE"} / {report["source"]["id"]}
Saved fit: {report["recipe"]["components"]} PCs / {report["recipe"]["endmembers"]} endmembers / {report["vca"]["projection"]} / seed {report["vca"]["seed"]}
{report["fcls"]["valid_cells"]} complete observed spectra; median RMSE {report["fcls"]["rmse_median"]:.6f}. Material fractions are unvalidated.""")
        directory = self.data_dir / "analyses" / report["id"]
        self.query_one("#spectral-exports", Static).update(f"""Report: {directory / "report.html"}
Reproduction: {directory / "request.json"}
COGs and complete bundle: {directory / "bundle.zip"}""")
        cell = report["vca"]["cells"][0]
        self.query_one("#sp-row", Input).value = str(cell["row"])
        self.query_one("#sp-col", Input).value = str(cell["column"])
        self.query_one("#tabs", TabbedContent).active = "spectral-tab"
        try:
            await self.display_spectral_cell()
        except (OSError, ValueError) as exc:
            self.set_status(
                f"Saved spectral artifacts are available; source cell inspection failed: {exc}"
            )
            return
        self.set_status(
            "Spectral report and artifacts available. Source run unchanged; fractions lack independent material validation."
        )

    def update_spectral_loadings(self):
        report = self.spectral_report
        if not report:
            return
        value = self.query_one("#sp-loading", Select).value
        if value == Select.BLANK:
            return
        i = int(str(value))
        table = self.query_one("#spectral-loadings", DataTable)
        table.clear()
        for k, band in enumerate(report["vca"]["bands"]):
            table.add_row(band, f"{report['pca']['loadings'][i][k]:.5f}")
        score = self.spectral_cell["scores"][i] if self.spectral_cell else None
        self.query_one("#sp-variance", Static).update(
            f"PC{i + 1}: {report['pca']['variance_fraction'][i]:.3%} variance / cell score {score if score is not None else 'missing'}. No whitening."
        )

    @work(group="spectral-cell", exclusive=True)
    async def inspect_spectral_cell(self):
        try:
            await self.display_spectral_cell()
        except Exception as exc:
            self.set_status(f"Spectral inspection failed: {exc}")

    async def display_spectral_cell(self):
        from rslib.spectral_workflow import inspect_spectra

        report = self.spectral_report
        if not report:
            raise ValueError("Open a completed spectral analysis first")
        row, col = (
            int(self.query_one("#sp-row", Input).value),
            int(self.query_one("#sp-col", Input).value),
        )
        self.spectral_cell = None
        self.update_spectral_loadings()
        self.query_one("#spectral-values", DataTable).clear()
        members = self.query_one("#spectral-members", DataTable)
        members.clear()
        for k, source in enumerate(report["vca"]["cells"]):
            members.add_row(f"E{k + 1}", f"{source['row']}, {source['column']}", "pending")
        async with self.job_runner.slots:
            cell = await asyncio.to_thread(
                inspect_spectra, self.data_dir / "analyses" / report["id"], self.data_dir, row, col
            )
        if not self.is_running or self.spectral_report["id"] != report["id"]:
            return

        self.spectral_cell = cell
        self.update_spectral_loadings()

        def number(value):
            return "missing" if value is None else f"{value:.5f}"

        table = self.query_one("#spectral-values", DataTable)
        table.clear()
        for k, band in enumerate(cell["bands"]):
            a, b = cell["observed"][k], cell["reconstructed"][k]
            table.add_row(
                band,
                number(a),
                number(b),
                number(b - a) if a is not None and b is not None else "missing",
            )
        members = self.query_one("#spectral-members", DataTable)
        members.clear()
        for k, source in enumerate(report["vca"]["cells"]):
            members.add_row(
                f"E{k + 1}", f"{source['row']}, {source['column']}", number(cell["abundance"][k])
            )
        self.set_status(
            f"Spectral cell {row}, {col} / {'observed' if cell['valid'] else 'missing or excluded'} / reflectance RMSE {number(cell['rmse'])}"
        )

    def action_jobs(self):
        self.refresh_jobs()
        self.query_one("#tabs", TabbedContent).active = "jobs-tab"

    def cancel_selected_job(self):
        if self.selected_job_id:
            self.jobs.cancel(self.selected_job_id)
            self.refresh_jobs()

    def retry_selected_job(self):
        if self.selected_job_id:
            self.jobs.retry(self.selected_job_id)
            self.refresh_jobs()

    def on_select_changed(self, event: Select.Changed):
        if event.select.id == "sp-loading" and self.spectral_report and event.value != Select.BLANK:
            self.update_spectral_loadings()
        if event.select.id == "sp-map" and self.spectral_report and event.value != Select.BLANK:
            if any(d["filename"] == event.value for d in self.spectral_report["displays"]):
                self.query_one("#spectral-raster", RasterView).set_image(
                    self.data_dir / "analyses" / self.spectral_report["id"] / str(event.value)
                )
        if event.select.id == "provider" and event.value != Select.BLANK:
            self.query_one("#collection", Input).value = (
                "sentinel-2-l2a" if event.value == "planetary-computer" else "sentinel-2-c1-l2a"
            )

    def set_status(self, text: str):
        self.query_one("#status", Static).update(text)

    def on_button_pressed(self, event: Button.Pressed):
        action = {
            "search": self.action_search,
            "demo": self.action_demo,
            "analyze": self.action_analyze,
            "hydro": self.action_hydro,
            "stack": self.action_stack,
            "cancel-job": self.cancel_selected_job,
            "retry-job": self.retry_selected_job,
            "open-job": self.open_selected_job,
            "compare-sensors": lambda: self.run_diagnostics("agreement"),
            "validate-series": lambda: self.run_diagnostics("validation"),
            "sp-load": self.load_spectral_sources,
            "sp-run": self.run_spectral_job,
            "sp-inspect": self.inspect_spectral_cell,
        }.get(event.button.id)
        if action:
            action()

    @work(group="diagnostics")
    async def run_diagnostics(self, kind: str):
        if self.diagnostics_busy:
            return
        if not self.last_stack:
            self.set_status("Open or prepare an optical run first.")
            return
        from rslib.agreement import compare_run
        from rslib.validation import validate_run

        self.query_one("#tabs", TabbedContent).active = "diagnostics-tab"
        summary = self.query_one("#diagnostics-summary", Static)
        summary.update("Computing on the immutable published stack…")
        table = self.query_one("#diagnostics-table", DataTable)
        table.clear(columns=True)
        identifier = self.last_stack["id"]
        self.diagnostics_busy = True
        for button in ["compare-sensors", "validate-series"]:
            self.query_one(f"#{button}", Button).disabled = True
        try:
            async with self.job_runner.slots:
                result = await asyncio.to_thread(
                    compare_run if kind == "agreement" else validate_run,
                    self.data_dir / "runs" / identifier,
                )
            if not self.is_running or not self.last_stack or self.last_stack["id"] != identifier:
                return
            label = "SYNTHETIC" if result["synthetic"] else "SATELLITE"

            def number(value):
                return "—" if value is None else f"{value:.5f}"

            if kind == "agreement":
                table.add_columns(
                    "Pair",
                    "Band / unit 1",
                    "Bias MSI−OLI",
                    "RMSE before",
                    "RMSE current",
                    "Correlation",
                )
                lines = [
                    f"{label} / sensor agreement / {len(result['pairs'])} accepted pairs; {len(result['unpaired_source_indices'])} unpaired sources",
                    "Closest UTC times, disjoint sources; common native-QA-clear complete spectra. Differences include real change, angles, atmosphere and registration; no ground-truth accuracy claim.",
                ]
                for i, pair in enumerate(result["pairs"], 1):
                    lines.append(
                        f"Pair {i}: {pair['reference']['id']} / {pair['comparison']['id']}\n{pair['separation_hours']:.2f} hours apart; {pair['common_clear_cells']} common clear cells; median spectral angle {number(pair['spectral_angle']['median'])}°"
                    )
                    for band in pair["bands"]:
                        before = band["before_local_bandpass"]
                        table.add_row(
                            str(i),
                            band["band"],
                            number(band["current"]["bias"]),
                            number(before["rmse"] if before else None),
                            number(band["current"]["rmse"]),
                            number(band["current"]["correlation"]),
                        )
                if not result["pairs"]:
                    lines.append(
                        "No pair met the default 48-hour/100-common-clear-cell requirements. Review the source inventory; the CLI and browser allow explicit limits."
                    )
                summary.update("\n\n".join(lines))
            else:
                table.add_columns(
                    "Held-out UTC",
                    "Clear cells",
                    "Scored %",
                    "Linear RMSE",
                    "Nearest RMSE",
                    "Bracket / d",
                )
                stats = result["summary"]
                summary.update(
                    f"{label} / whole-date holdouts across all sensors\n{stats['scored_cells']} / {stats['held_out_clear_cells']} clear cell dates scorable; {stats['scored_dates']} / {result['acquisition_days']} dates.\nLinear RMSE {number(stats['linear']['rmse'])}; paired nearest RMSE {number(stats['nearest']['rmse'])}.\nClear measurements are a reference, not independent ground truth. Edge dates remain unscorable; correlated pixels are not independent replicates."
                )
                for fold in result["folds"]:
                    table.add_row(
                        fold["day"],
                        str(fold["held_out_clear_cells"]),
                        "—"
                        if fold["scored_fraction"] is None
                        else f"{fold['scored_fraction']:.1%}",
                        number(fold["linear"]["rmse"]),
                        number(fold["nearest"]["rmse"]),
                        number(fold["median_bracket_days"]),
                    )
            self.set_status(f"Quantitative {kind} check available; source SHA256 verified.")
        except Exception as exc:
            if self.is_running:
                summary.update(f"Check could not be completed: {exc}")
                self.set_status(f"Quantitative check failed: {exc}")
        finally:
            self.diagnostics_busy = False
            if self.is_running:
                for button in ["compare-sensors", "validate-series"]:
                    self.query_one(f"#{button}", Button).disabled = False

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        if event.data_table.id == "spectral-members" and self.spectral_report:
            cell = self.spectral_report["vca"]["cells"][event.cursor_row]
            self.query_one("#sp-row", Input).value = str(cell["row"])
            self.query_one("#sp-col", Input).value = str(cell["column"])
            self.inspect_spectral_cell()
            return
        if event.data_table.id == "jobs-table":
            self.selected_job_id = str(event.row_key.value)
            self.refresh_jobs()
            return
        if event.data_table.id != "scene-table":
            return
        self.selected = event.cursor_row
        if self.scenes:
            self.set_status(f"Selected {self.scenes[self.selected]['id']}")

    def fill_scenes(self):
        table = self.query_one("#scene-table", DataTable)
        table.clear()
        for f in self.scenes:
            p = f.get("properties", {})
            table.add_row(
                str(p.get("datetime", "unknown"))[:10], str(p.get("eo:cloud_cover", "—"))[:5]
            )
        self.selected = 0

    def action_demo(self):
        if not self.working:
            self.load_demo()

    @work(exclusive=True, group="discovery")
    async def load_demo(self):
        self.working = True
        try:
            fixture = await asyncio.to_thread(create_demo, self.data_dir / "demo")
            self.active_provider, self.scenes = "demo", fixture["features"]
            self.active_bbox = BBox(west=-44.75, south=-22.5, east=-44.55, north=-22.3)
            self.fill_scenes()
            self.set_status("SYNTHETIC DEMO · 3 fixture dates, identical rasters · a to analyze")
        finally:
            self.working = False

    def action_search(self):
        if self.working:
            return
        if self.query_one("#provider", Select).value == "demo":
            self.action_demo()
        else:
            self.search_catalog()

    @work(exclusive=True, group="discovery")
    async def search_catalog(self):
        self.working = True
        try:
            west, south, east, north = map(float, self.query_one("#bbox", Input).value.split(","))
            bbox = BBox(west=west, south=south, east=east, north=north)
            cloud = self.query_one("#cloud", Input).value
            provider = str(self.query_one("#provider", Select).value)
            query = Search(
                provider=provider,
                collections=[self.query_one("#collection", Input).value],
                bbox=bbox,
                datetime=self.query_one("#dates", Input).value or None,
                max_cloud=float(cloud) if cloud else None,
            )
            self.set_status("Searching STAC in background…")
            result = await client_for(provider, self.cache).search(query)
            self.active_provider, self.scenes, self.active_bbox = provider, result["features"], bbox
            self.fill_scenes()
            self.set_status(
                f"{len(self.scenes)} scenes · bounded={result['rslib']['truncated']} · {result['rslib']['ranking']}"
            )
        except Exception as exc:
            self.set_status(f"Search failed: {exc}")
        finally:
            self.working = False

    def action_analyze(self):
        if not self.working:
            self.run_analysis()

    @work(exclusive=True, group="analysis")
    async def run_analysis(self):
        if not self.scenes:
            self.set_status("Load a demo or search for scenes first.")
            return
        self.working = True
        try:
            scene = self.scenes[self.selected]
            index = str(self.query_one("#index", Select).value)
            request = AnalysisRequest(
                provider=self.active_provider,
                collection=scene["collection"],
                item_id=scene["id"],
                bbox=self.active_bbox,
                index=index,
                size=256,
            )
            self.set_status("Reading bounded windows and applying pixel quality masks…")
            report = await asyncio.to_thread(analyze_scene, scene, request, self.data_dir / "runs")
            directory = self.data_dir / "runs" / report["id"]
            self.query_one("#raster", RasterView).set_image(directory / "preview.png")
            import json

            self.query_one("#summary", Static).update(
                f"{'SYNTHETIC' if report['synthetic'] else 'LIVE'} / {index.upper()}\n\n"
                + json.dumps(report["statistics"], indent=2)
                + f"\n\n{directory}"
            )
            self.query_one("#provenance", Static).update(json.dumps(report, indent=2))
            self.query_one("#tabs", TabbedContent).active = "raster-tab"
            self.set_status(
                f"Complete in {report['elapsed_seconds']} s · sampled preview statistics · COG/report saved"
            )
        except Exception as exc:
            self.set_status(f"Analysis failed: {exc}")
        finally:
            self.working = False

    def action_hydro(self):
        if not self.working:
            self.run_hydro()

    def action_stack(self):
        if not self.working:
            self.run_stack()

    @work(exclusive=True, group="analysis")
    async def run_stack(self):
        import json

        from rslib.jobs import JobSpec
        from rslib.stack_demo import DEMO_BBOX
        from rslib.workflows import StackRequest

        self.working = True
        try:
            demo = self.query_one("#provider", Select).value == "demo"
            if demo:
                self.query_one("#bbox", Input).value = ",".join(map(str, DEMO_BBOX.bounds))
            bbox = (
                DEMO_BBOX
                if demo
                else BBox(
                    **dict(
                        zip(
                            ("west", "south", "east", "north"),
                            map(float, self.query_one("#bbox", Input).value.split(",")),
                            strict=True,
                        )
                    )
                )
            )
            index = str(self.query_one("#index", Select).value)
            if index == "rgb":
                raise ValueError("Choose a scalar index for the optical time series")
            recipe = dict(self.project["recipe"]) if self.project else {}
            recipe.update(
                demo=demo,
                bbox=bbox,
                datetime=self.query_one("#dates", Input).value,
                step_days=int(self.query_one("#stack-step", Input).value),
                max_gap_days=float(self.query_one("#stack-gap", Input).value),
                index=index,
                max_cloud=float(self.query_one("#cloud", Input).value or "100"),
            )
            request = StackRequest(**recipe)
            if self.project:
                from rslib.projects import ProjectUpdate

                self.project = self.projects.update(
                    self.project["id"],
                    ProjectUpdate(
                        name=self.project["name"], recipe=request, revision=self.project["revision"]
                    ),
                )
            spec = (
                JobSpec(project_id=self.project["id"], revision=self.project["revision"])
                if self.project
                else JobSpec(recipe=request)
            )
            job = self.jobs.submit(spec)
            self.selected_job_id = job["id"]
            self.action_jobs()
            while True:
                job = self.jobs.get_job(job["id"])
                self.set_status(f"{job['status']}: {job['progress'].get('message', '')}")
                if job["status"] in {"succeeded", "failed", "cancelled"}:
                    break
                await asyncio.sleep(0.2)
            if job["status"] != "succeeded":
                self.set_status(
                    (job["error"] or {}).get(
                        "message", "Job cancelled. Completed scenes remain cached."
                    )
                )
                return
            report = json.loads(
                (self.data_dir / "runs" / job["run_id"] / "manifest.json").read_text()
            )
            if self.project:
                self.project = self.projects.get(self.project["id"])
            self.last_stack, self.stack_frame, self.stack_support = report, 0, False
            self.query_one("#summary", Static).update(
                ("SYNTHETIC" if demo else "LIVE")
                + " / OPTICAL STACK\n\n"
                + json.dumps(report["summary"], indent=2)
                + "\n\n[ ] dates · g support\n"
                + str(self.data_dir / "runs" / report["id"])
            )
            self.query_one("#provenance", Static).update(json.dumps(report, indent=2))
            self.show_stack_frame()
        except Exception as exc:
            self.set_status(f"Optical stack failed: {exc}")
        finally:
            self.working = False

    def show_stack_frame(self):
        if not self.last_stack:
            self.set_status("Prepare an optical stack with w first.")
            return
        frame = self.last_stack["timeline"][self.stack_frame]
        name = f"{'support' if self.stack_support else 'frame'}-{self.stack_frame:04d}.png"
        self.query_one("#raster", RasterView).set_image(
            self.data_dir / "runs" / self.last_stack["id"] / name
        )
        tabs = self.query_one("#tabs", TabbedContent)
        if tabs.active != "areas-tab":
            tabs.active = "raster-tab"
        label = "SYNTHETIC" if self.last_stack["synthetic"] else "LIVE"
        self.set_status(
            f"{label} / {frame['day']} · {frame['observed_fraction']:.1%} observed · {frame['filled_fraction']:.1%} interpolated · [ ] dates / g support"
        )
        table = self.query_one("#area-table", DataTable)
        table.clear()
        for field in self.last_stack.get("fields", []):
            sample = field["timeline"][self.stack_frame]
            table.add_row(
                field["name"],
                f"{field['area_m2'] / 10000:.2f}",
                f"{sample['observed_fraction']:.1%}",
                f"{sample['estimated_fraction']:.1%}",
                f"{sample['missing_fraction']:.1%}",
                f"{sample['observed_mean']:.4f}" if sample["observed_mean"] is not None else "—",
            )
        self.query_one("#areas-date", Static).update(
            f"{label} · {frame['day']} · projected fractional-cell areas"
        )
        self.query_one("#areas-note", Static).update(
            f"CSV: {self.data_dir / 'runs' / self.last_stack['id'] / 'fields.csv'}"
        )
        history = self.query_one("#area-history-table", DataTable)
        history.clear()
        lo, hi = (
            max(0, self.stack_frame - 15),
            min(len(self.last_stack["timeline"]), self.stack_frame + 16),
        )
        for i in range(lo, hi):
            for field in self.last_stack.get("fields", []):
                sample = field["timeline"][i]
                history.add_row(
                    sample["day"],
                    field["name"],
                    f"{sample['observed_fraction']:.1%}",
                    f"{sample['estimated_fraction']:.1%}",
                    f"{sample['missing_fraction']:.1%}",
                    f"{sample['observed_mean']:.4f}"
                    if sample["observed_mean"] is not None
                    else "—",
                    f"{sample['supported_mean']:.4f}"
                    if sample["supported_mean"] is not None
                    else "—",
                )

    def action_fields(self):
        self.query_one("#tabs", TabbedContent).active = "areas-tab"

    def action_next_frame(self):
        if self.last_stack and not self.working:
            self.stack_frame = min(len(self.last_stack["timeline"]) - 1, self.stack_frame + 1)
            self.show_stack_frame()

    def action_previous_frame(self):
        if self.last_stack and not self.working:
            self.stack_frame = max(0, self.stack_frame - 1)
            self.show_stack_frame()

    def action_support(self):
        if self.last_stack and not self.working:
            self.stack_support = not self.stack_support
            self.show_stack_frame()

    @work(exclusive=True, group="analysis")
    async def run_hydro(self):
        from rslib.hydro import demo_problem, simulate

        self.working = True
        try:
            self.set_status("Running native Rust pressure diffusion…")
            result = await asyncio.to_thread(simulate, demo_problem())
            c = result["cells"][0]
            rows = [
                "SYNTHETIC STORM / native Rust wet-column model",
                f"Minimum FS: {c['minimum_factor_of_safety']:.4f}",
                f"Critical depth: {c['critical_depth_m']} m; time: {c['critical_time_s'] / 3600} h",
                "",
                "Hour     Minimum FS at sampled depths",
            ]
            for t in sorted({s["time_s"] for s in c["samples"]}):
                fs = min(s["factor_of_safety"] for s in c["samples"] if s["time_s"] == t)
                rows.append(
                    f"{t / 3600:5.1f}    {fs:8.4f}  " + "▉" * min(40, max(0, round(fs * 12)))
                )
            rows.extend(["", *result["limitations"]])
            self.query_one("#hydro-text", Static).update("\n".join(rows))
            self.query_one("#tabs", TabbedContent).active = "hydro-tab"
            self.set_status(
                "Rust scenario complete · research model, not a validated hazard forecast"
            )
        except Exception as exc:
            self.set_status(str(exc))
        finally:
            self.working = False
