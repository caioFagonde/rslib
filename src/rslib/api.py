from __future__ import annotations

import asyncio
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from rasterio.errors import RasterioError

from rslib import __version__
from rslib.cache import ResponseCache
from rslib.catalog import PROVIDERS, SOURCES
from rslib.demo import create_demo
from rslib.jobs import JobConflict, JobRunner, Jobs, JobSpec
from rslib.models import AnalysisRequest, BBox, Search
from rslib.pipeline import analyze_scene
from rslib.projects import ProjectConflict, ProjectRun, Projects, ProjectSpec, ProjectUpdate
from rslib.stac import CatalogError, client_for
from rslib.workflows import StackRequest, inspect_pixel, prepare_optical


class HydroDemo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rainfall_mm_h: float = Field(default=18, ge=0, le=300, allow_inf_nan=False)


class SurfaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bbox: BBox
    size: int = Field(default=256, ge=64, le=512)


def create_app(data_dir: Path | None = None) -> FastAPI:
    data = Path(data_dir or os.environ.get("RSLIB_DATA", "data")).resolve()
    cache = ResponseCache(data / "cache" / "stac.sqlite3")
    analysis_slots = asyncio.Semaphore(2)
    jobs = Jobs(data / "projects.sqlite3")
    runner = JobRunner(data, jobs, analysis_slots, cache)

    @asynccontextmanager
    async def lifespan(app):
        await runner.start()
        try:
            yield
        finally:
            await runner.stop()

    app = FastAPI(title="RSLIB Earth observation workbench", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    search_slots = asyncio.Semaphore(8)
    projects = Projects(data / "projects.sqlite3")

    async def job_call(method, *args):
        try:
            return await asyncio.to_thread(method, *args)
        except KeyError as exc:
            raise HTTPException(404, "Job or project not found") from exc
        except (JobConflict, ProjectConflict) as exc:
            raise HTTPException(409, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, "Source run or artifact not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/jobs", status_code=202)
    async def job_submit(spec: JobSpec):
        return await job_call(jobs.submit, spec)

    @app.get("/api/jobs")
    async def job_list(
        project_id: str | None = None,
        source_run_id: str | None = Query(default=None, pattern=r"^[a-f0-9]{32}$"),
    ):
        return {"jobs": await job_call(jobs.list_jobs, project_id, source_run_id)}

    @app.get("/api/jobs/{identifier}")
    async def job_get(identifier: str):
        return await job_call(jobs.get_job, identifier)

    @app.get("/api/jobs/{identifier}/events")
    async def job_events(identifier: str, after: int = Query(default=0, ge=0)):
        return {"events": await job_call(jobs.events, identifier, after)}

    @app.post("/api/jobs/{identifier}/cancel")
    async def job_cancel(identifier: str):
        return await job_call(jobs.cancel, identifier)

    @app.post("/api/jobs/{identifier}/retry", status_code=202)
    async def job_retry(identifier: str):
        return await job_call(jobs.retry, identifier)

    @app.get("/api/runs/{identifier}/validation")
    async def temporal_validation(identifier: str):
        from rslib.validation import validate_run

        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise HTTPException(404, "Run not found")
        directory = data / "runs" / identifier
        if not (directory / "manifest.json").exists():
            raise HTTPException(404, "Run not found")
        try:
            async with analysis_slots:
                return await asyncio.to_thread(validate_run, directory)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/runs/{identifier}/agreement")
    async def sensor_agreement(
        identifier: str,
        max_hours: float = Query(default=48, gt=0, le=168),
        min_cells: int = Query(default=100, ge=1, le=1048576),
    ):
        from rslib.agreement import compare_run

        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise HTTPException(404, "Run not found")
        directory = data / "runs" / identifier
        if not (directory / "manifest.json").exists():
            raise HTTPException(404, "Run not found")
        try:
            async with analysis_slots:
                return await asyncio.to_thread(
                    compare_run, directory, max_hours=max_hours, min_cells=min_cells
                )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/projects")
    async def project_list():
        return {"projects": await asyncio.to_thread(projects.list)}

    @app.post("/api/projects")
    async def project_create(spec: ProjectSpec):
        return await asyncio.to_thread(projects.create, spec)

    @app.get("/api/projects/{identifier}")
    async def project_get(identifier: str):
        try:
            return await asyncio.to_thread(projects.get, identifier)
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc

    @app.post("/api/projects/{identifier}")
    async def project_update(identifier: str, spec: ProjectUpdate):
        try:
            return await asyncio.to_thread(projects.update, identifier, spec)
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc
        except ProjectConflict as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/projects/{identifier}/runs")
    async def project_run(identifier: str, spec: ProjectRun):
        try:
            project = await asyncio.to_thread(projects.get, identifier)
            if spec.revision != project["revision"]:
                raise HTTPException(
                    409, "Project changed before execution. Reload it before running."
                )
            report = await stack_workflow(StackRequest(**project["recipe"]))
            await asyncio.to_thread(projects.attach, identifier, project["revision"], report)
            return report
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc

    @app.post("/api/stack")
    async def stack_workflow(request: StackRequest):
        try:
            async with analysis_slots:
                return await prepare_optical(request, data, catalog_cache=cache)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (httpx.HTTPError, CatalogError, RasterioError) as exc:
            raise HTTPException(
                502,
                "An optical source could not be prepared. Completed scene work is cached; retry the recipe.",
            ) from exc

    @app.post("/api/surface")
    async def surface(query: SurfaceRequest):
        from rslib.surface import build_surface

        try:
            async with analysis_slots:
                search = Search(
                    bbox=query.bbox,
                    collections=["cop-dem-glo-30"],
                    datetime=None,
                    max_cloud=None,
                    max_items=8,
                    max_pages=1,
                )
                found = await client_for("earth-search", cache).search(search)
                return await asyncio.to_thread(
                    build_surface, found["features"], query.bbox, data / "runs", query.size
                )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (httpx.HTTPError, CatalogError, RasterioError) as exc:
            raise HTTPException(
                502, "Elevation source unavailable; retry or continue in 2D"
            ) from exc

    @app.post("/api/hydro/demo")
    async def hydro_demo(query: HydroDemo):
        from rslib.hydro import demo_problem, simulate

        problem = demo_problem()
        problem["rain"][0]["intensity_m_s"] = query.rainfall_mm_h / 3_600_000
        try:
            async with analysis_slots:
                result = await asyncio.to_thread(simulate, problem)
            return {
                **result["cells"][0],
                "water_balance": result["water_balance"],
                "limitations": result["limitations"],
                "synthetic": True,
            }
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": __version__, "analysis_concurrency": 2}

    @app.get("/api/sources")
    async def sources():
        return {"sources": SOURCES, "providers": PROVIDERS}

    @app.get("/api/collections/{provider}")
    async def collections(provider: str):
        if provider not in PROVIDERS:
            raise HTTPException(404, "Unknown provider")
        try:
            async with search_slots:
                values = await client_for(provider, cache).collections()
            return {
                "collections": [
                    {
                        "id": v["id"],
                        "title": v.get("title", v["id"]),
                        "description": v.get("description", ""),
                        "license": v.get("license"),
                        "extent": v.get("extent"),
                    }
                    for v in values
                ]
            }
        except (httpx.HTTPError, CatalogError) as exc:
            raise HTTPException(
                502, "Catalog unavailable; retry or use the explicitly labeled demo"
            ) from exc

    @app.get("/api/demo")
    async def demo():
        fixture = await asyncio.to_thread(create_demo, data / "demo")
        # Browser does not need local asset paths. Analysis resolves the trusted fixture internally.
        return {**fixture, "features": [{**f, "assets": {}} for f in fixture["features"]]}

    @app.post("/api/search")
    async def search(query: Search):
        try:
            async with search_slots:
                result = await client_for(query.provider, cache).search(query)
                from rslib.planner import plan_coverage

                result["rslib"]["coverage_plan"] = await asyncio.to_thread(
                    plan_coverage, result["features"], query.bbox
                )
                return result
        except (httpx.HTTPError, CatalogError) as exc:
            raise HTTPException(
                502, "STAC search failed; verify collection/date filters or retry"
            ) from exc

    @app.post("/api/analyze")
    async def analyze(request: AnalysisRequest):
        try:
            async with analysis_slots:
                if request.provider == "demo":
                    fixture = await asyncio.to_thread(create_demo, data / "demo")
                    item = next(
                        (
                            f
                            for f in fixture["features"]
                            if f["id"] == request.item_id and f["collection"] == request.collection
                        ),
                        None,
                    )
                    if item is None:
                        raise HTTPException(404, "Unknown demo scene")
                else:
                    item = await client_for(request.provider, cache).item(
                        request.collection, request.item_id
                    )
                return await asyncio.to_thread(analyze_scene, item, request, data / "runs")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (httpx.HTTPError, CatalogError, RasterioError) as exc:
            raise HTTPException(
                502, "Source raster could not be read; retry or inspect catalog asset availability"
            ) from exc

    @app.get("/api/runs/{run_id}/pixel")
    async def pixel(
        run_id: str,
        row: int | None = None,
        col: int | None = None,
        longitude: float | None = None,
        latitude: float | None = None,
    ):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise HTTPException(404, "Unknown run")
        directory = data / "runs" / run_id
        if not (directory / "series-support.tif").is_file():
            raise HTTPException(404, "Pixel inspection requires a new optical stack run")
        try:
            async with analysis_slots:
                return await asyncio.to_thread(
                    inspect_pixel, directory, row, col, longitude=longitude, latitude=latitude
                )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/analyses/{identifier}/pixel")
    async def spectral_pixel(identifier: str, row: int = Query(ge=0), col: int = Query(ge=0)):
        from rslib.spectral_workflow import inspect_spectra

        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise HTTPException(404, "Analysis not found")
        try:
            async with analysis_slots:
                return await asyncio.to_thread(
                    inspect_spectra, data / "analyses" / identifier, data, row, col
                )
        except FileNotFoundError as exc:
            raise HTTPException(404, "Analysis or source not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/analyses/{identifier}/{filename}")
    async def spectral_artifact(identifier: str, filename: str):
        allowed = {
            "report.json": "application/json",
            "request.json": "application/json",
            "report.html": "text/html",
            "bundle.zip": "application/zip",
            "pca.tif": "image/tiff",
            "abundance.tif": "image/tiff",
            "reconstruction-rmse.tif": "image/tiff",
        }
        if filename in {"rgb.png", "pca.png", "abundance.png", "rmse.png"} or re.fullmatch(
            r"(?:pc|endmember)-0[1-6]\.png", filename
        ):
            allowed[filename] = "image/png"
        if not re.fullmatch(r"[a-f0-9]{32}", identifier) or filename not in allowed:
            raise HTTPException(404, "Unknown analysis artifact")
        directory = data / "analyses" / identifier
        if not (directory / "report.json").is_file() or not (directory / filename).is_file():
            raise HTTPException(404, "Published analysis artifact not found")
        if filename == "report.json":
            from rslib.spectral_workflow import load_spectral_report

            try:
                async with analysis_slots:
                    await asyncio.to_thread(load_spectral_report, directory)
            except (ValueError, FileNotFoundError) as exc:
                raise HTTPException(
                    422, "Published spectral artifacts failed checksum verification"
                ) from exc
        return FileResponse(
            directory / filename,
            media_type=allowed[filename],
            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"},
        )

    @app.get("/api/runs/{run_id}/{filename}")
    async def artifact(run_id: str, filename: str):
        types = {
            "preview.png": "image/png",
            "analysis.tif": "image/tiff",
            "report.html": "text/html",
            "manifest.json": "application/json",
            "elevation.png": "image/png",
            "elevation.tif": "image/tiff",
            "before.png": "image/png",
            "stack.npz": "application/octet-stream",
            "series.npz": "application/octet-stream",
            "series-support.tif": "image/tiff",
            "composite.tif": "image/tiff",
            "provenance.tif": "image/tiff",
            "map-composite.png": "image/png",
            "fields.csv": "text/csv",
            "fields.geojson": "application/geo+json",
        }
        if re.fullmatch(r"(?:map-)?(?:frame|support)-\d{4}\.png", filename):
            types[filename] = "image/png"
        if not re.fullmatch(r"[a-f0-9]{32}", run_id) or filename not in types:
            raise HTTPException(404, "Unknown artifact")
        path = data / "runs" / run_id / filename
        if not path.is_file():
            raise HTTPException(404, "Artifact not found")
        return FileResponse(
            path,
            media_type=types[filename],
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )

    web = Path(__file__).parent / "web"
    if web.is_dir():
        app.mount("/", StaticFiles(directory=web, html=True), name="browser")
    return app
