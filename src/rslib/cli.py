from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import typer
from rich import print

from rslib.cache import ResponseCache
from rslib.demo import create_demo
from rslib.models import AnalysisRequest, BBox, Search
from rslib.pipeline import analyze_scene
from rslib.stac import client_for

app = typer.Typer(
    no_args_is_help=True, help="RSLIB — cloud-native remote sensing and native Rust slope analysis"
)
project_app = typer.Typer(help="List or execute locally saved monitoring projects.")
app.add_typer(project_app, name="project")
job_app = typer.Typer(
    help="Submit and inspect the durable local preparation queue. Start rslib serve to process it."
)
app.add_typer(job_app, name="jobs")


@job_app.command("submit")
def job_submit(
    recipe: Path | None = None,
    project: str | None = None,
    data: Path = Path("data"),
    spec: Path | None = None,
):
    """Snapshot a JSON recipe or saved project into the server's durable queue."""
    from rslib.jobs import Jobs, JobSpec
    from rslib.workflows import StackRequest

    if sum(value is not None for value in (recipe, project, spec)) != 1:
        raise typer.BadParameter("Provide exactly one of --recipe, --project or --spec")
    store = Jobs(data / "projects.sqlite3")
    submission = (
        JobSpec.model_validate_json(spec.read_text())
        if spec
        else (
            JobSpec(project_id=project, revision=store.get(project)["revision"])
            if project
            else JobSpec(recipe=StackRequest.model_validate_json(recipe.read_text()))
        )
    )
    typer.echo(json.dumps(store.submit(submission), indent=2))


@job_app.command("list")
def job_list(data: Path = Path("data")):
    """Inspect queue states and the last measured processing checkpoint."""
    from rich.table import Table

    from rslib.jobs import Jobs

    table = Table("Job", "State", "Attempt", "Last checkpoint")
    for job in Jobs(data / "projects.sqlite3").list_jobs():
        table.add_row(
            job["id"], job["status"], str(job["attempt"]), job["progress"].get("message", "")
        )
    print(table)


@job_app.command("show")
def job_show(identifier: str, data: Path = Path("data")):
    from rslib.jobs import Jobs

    typer.echo(json.dumps(Jobs(data / "projects.sqlite3").get_job(identifier), indent=2))


@job_app.command("cancel")
def job_cancel(identifier: str, data: Path = Path("data")):
    from rslib.jobs import Jobs

    typer.echo(json.dumps(Jobs(data / "projects.sqlite3").cancel(identifier), indent=2))


@job_app.command("retry")
def job_retry(identifier: str, data: Path = Path("data")):
    from rslib.jobs import Jobs

    typer.echo(json.dumps(Jobs(data / "projects.sqlite3").retry(identifier), indent=2))


@app.command("validate-series")
def temporal_validation(run: Path, output: Path | None = None):
    """Withhold complete acquisition days and compare interpolation with a paired nearest baseline."""
    from rslib.validation import validate_run

    result = validate_run(run)
    text = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)
    print(result["summary"])


@app.command("spectral-analysis")
def spectral_analysis(
    run: Path,
    output: Path,
    source_index: int = 0,
    endmembers: int = 3,
    seed: int = 0,
    components: int = 3,
    projection: str = "affine",
):
    """Fit observed-scene PCA/VCA and export constrained fractions and residual COGs."""
    from rslib.spectral_workflow import analyze_spectra

    result = analyze_spectra(
        run,
        output,
        source_index=source_index,
        endmembers=endmembers,
        seed=seed,
        components=components,
        projection=projection,
    )
    print({"source": result["source"]["id"], "output": str(output), **result["fcls"]})


@app.command("reference-check")
def reference_check(
    identifier: str,
    catalog: Path = Path("docs/reference-projects/catalog.json"),
    data: Path = Path("data"),
):
    """Verify a frozen local input snapshot; no acquisition or accuracy claim."""
    from rslib.references import check_reference

    typer.echo(json.dumps(check_reference(catalog, data, identifier), indent=2))


@app.command("reference-acquire")
def reference_acquire(
    identifier: str,
    plan: Path = Path("docs/reference-projects/selection-plan.json"),
    snapshots: Path = Path("docs/reference-projects/snapshots"),
    data: Path = Path("data"),
):
    """Pin public STAC/collection metadata, prepare or resume one selected reference."""
    from rslib.reference_capture import acquire_reference

    result = asyncio.run(acquire_reference(plan, identifier, data, snapshots))
    typer.echo(json.dumps(result, indent=2))


@app.command("reference-audit")
def reference_audit(
    catalog: Path = Path("docs/reference-projects/catalog.json"),
    data: Path = Path("data"),
    output: Path | None = None,
):
    """Verify all frozen inputs and measure source support and paired diagnostics."""
    from rslib.references import audit_references

    value = json.dumps(audit_references(catalog, data), indent=2, allow_nan=False) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(value)
    else:
        typer.echo(value, nl=False)


@app.command("reference-register")
def reference_register(
    snapshot: Path,
    catalog: Path = Path("docs/reference-projects/catalog.json"),
    data: Path = Path("data"),
):
    """Register a verified capture without replacing an existing frozen reference."""
    from rslib.references import register_reference

    typer.echo(json.dumps(register_reference(catalog, data, snapshot), indent=2))


@app.command("compare-sensors")
def compare_sensors(
    run: Path, max_hours: float = 48, min_cells: int = 100, output: Path | None = None
):
    """Compare disjoint near-coincident Landsat/Sentinel pairs on common clear cells."""
    from rslib.agreement import compare_run

    result = compare_run(run, max_hours=max_hours, min_cells=min_cells)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    for pair in result["pairs"]:
        print(
            {
                "reference": pair["reference"]["id"],
                "comparison": pair["comparison"]["id"],
                "separation_hours": pair["separation_hours"],
                "common_clear_cells": pair["common_clear_cells"],
                "ndvi": pair["ndvi"],
            }
        )
    if not result["pairs"]:
        print("No pair met both the timestamp and common-clear-cell requirements.")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, data: Path = Path("data")):
    """Serve the API and built browser. Run npm run build in web/ first."""
    import uvicorn

    from rslib.api import create_app

    uvicorn.run(create_app(data), host=host, port=port)


@app.command()
def tui(data: Path = Path("data"), project: str | None = None):
    """Start the responsive terminal workbench, including true-color raster previews."""
    from rslib.tui import Workbench

    Workbench(data, project_id=project).run()


@app.command()
def demo(output: Path = Path("data"), index: str = "ndvi", size: int = 512):
    """Run an offline synthetic scene end-to-end. No remote data or model weights."""
    fixture = create_demo(output / "demo")
    request = AnalysisRequest(index=index, size=size)
    report = analyze_scene(fixture["features"][0], request, output / "runs")
    print(f"[bold yellow]SYNTHETIC DEMO[/bold yellow] · {report['elapsed_seconds']} s")
    typer.echo(json.dumps(report["statistics"], indent=2))
    print(f"Report: {(output / 'runs' / report['id'] / 'report.html').resolve()}")


@app.command()
def search(
    bbox: str,
    collection: str = "sentinel-2-c1-l2a",
    provider: str = "earth-search",
    dates: str | None = "2026-06-01/2026-08-01",
    cloud: float = 30,
    limit: int = 30,
    output: Path | None = None,
):
    """Search STAC. Use --cloud -1 to disable the cloud filter, --dates '' for DEMs."""
    west, south, east, north = map(float, bbox.split(","))
    query = Search(
        provider=provider,
        bbox=BBox(west=west, south=south, east=east, north=north),
        collections=[collection],
        datetime=dates or None,
        max_cloud=None if cloud < 0 else cloud,
        max_items=limit,
    )
    result = asyncio.run(
        client_for(provider, ResponseCache(Path("data/cache/stac.sqlite3"))).search(query)
    )
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n")
    else:
        typer.echo(json.dumps(result, indent=2))


@app.command()
def analyze(
    item: Path,
    provider: str = "earth-search",
    bbox: str = "-44.75,-22.5,-44.55,-22.3",
    index: str = "ndvi",
    output: Path = Path("data/runs"),
    size: int = 512,
):
    """Analyze a trusted local STAC Item JSON (or first feature of a saved search)."""
    doc = json.loads(item.read_text())
    if doc.get("type") == "FeatureCollection":
        if not doc["features"]:
            raise typer.BadParameter("Saved search has no scenes")
        doc = doc["features"][0]
    w, s, e, n = map(float, bbox.split(","))
    request = AnalysisRequest(
        provider=provider,
        collection=doc["collection"],
        item_id=doc["id"],
        bbox=BBox(west=w, south=s, east=e, north=n),
        index=index,
        size=size,
    )
    result = analyze_scene(doc, request, output)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def hydro(problem: Path, output: Path = Path("data/hydro/result.json")):
    """Run our Rust wet-infiltration / slope kernel from an SI-unit problem JSON."""
    from rslib.hydro import simulate

    result = simulate(json.loads(problem.read_text()))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(f"[green]Native simulation complete[/green] · {len(result['cells'])} cells · {output}")


@app.command("hydro-demo")
def hydro_demo(output: Path = Path("data/hydro")):
    """Save a hypothetical storm input and run it through the Rust kernel."""
    from rslib.hydro import demo_problem, simulate

    output.mkdir(parents=True, exist_ok=True)
    problem = demo_problem()
    (output / "problem.json").write_text(json.dumps(problem, indent=2) + "\n")
    result = simulate(problem)
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        f"SYNTHETIC SCENARIO · minimum FS {result['cells'][0]['minimum_factor_of_safety']:.4f} · {output}"
    )


@app.command()
def ingest(items: Path, dsn: str | None = None):
    """Persist a saved STAC search in the optional PostGIS catalog."""
    from rslib.store import PostGISCatalog

    url = dsn or os.environ.get("RSLIB_DATABASE_URL")
    if not url:
        raise typer.BadParameter("Set RSLIB_DATABASE_URL or supply --dsn")
    doc = json.loads(items.read_text())
    count = PostGISCatalog(url).ingest(
        doc["features"] if doc.get("type") == "FeatureCollection" else [doc]
    )
    print(f"Indexed {count} scenes in PostGIS")


@app.command()
def stack(
    bbox: str = "-44.66,-22.41,-44.64,-22.39",
    dates: str = "2026-06-01/2026-07-16",
    live: bool = False,
    resolution: float = 30,
    step: int = 5,
    max_gap: float = 20,
    limit: int = 4,
    cloud: float = 40,
    index: str = "ndvi",
    refresh: bool = False,
    coverage_target: float | None = None,
    areas: Path | None = None,
    data: Path = Path("data"),
):
    """Prepare a common-grid Sentinel-2/Landsat stack, mosaics and gap-limited series.

    Default is an explicitly synthetic multi-grid fixture. --live discovers real
    Sentinel-2 C1 and Landsat C2 scenes. Repeating a recipe reuses prepared scenes.
    """
    from rslib.fields import FieldBoundary
    from rslib.workflows import StackRequest, prepare_optical

    w, s, e, n = map(float, bbox.split(","))
    request = StackRequest(
        demo=not live,
        bbox=BBox(west=w, south=s, east=e, north=n),
        datetime=dates,
        resolution=resolution,
        step_days=step,
        max_gap_days=max_gap,
        max_scenes_per_sensor=limit,
        max_cloud=cloud,
        index=index,
        refresh=refresh,
        coverage_target=coverage_target,
        fields=[
            FieldBoundary(
                id=str(f.get("id", f"area-{i + 1}")),
                name=str(f.get("properties", {}).get("name", f"Area {i + 1}")),
                geometry=f["geometry"],
            )
            for i, f in enumerate(json.loads(areas.read_text())["features"])
        ]
        if areas
        else [],
    )

    report = asyncio.run(prepare_optical(request, data))
    print("SYNTHETIC MULTI-SENSOR FIXTURE" if request.demo else "ACTUAL MULTI-SENSOR DATA")
    print(report["summary"])
    print(
        f"Artifacts: {(data / 'runs' / report['id']).resolve()} · {report['elapsed_seconds']:.3f} s"
    )


@project_app.command("list")
def project_list(data: Path = Path("data")):
    """List project IDs, names and monitoring-area counts."""
    from rich.table import Table

    from rslib.projects import Projects

    table = Table("ID", "Name", "Areas", "Revision")
    for project in Projects(data / "projects.sqlite3").list():
        table.add_row(
            project["id"], project["name"], str(project["field_count"]), str(project["revision"])
        )
    print(table)


@project_app.command("run")
def project_run(identifier: str, data: Path = Path("data")):
    """Execute a saved recipe and record its run in the project's history."""
    from rslib.projects import Projects
    from rslib.workflows import StackRequest, prepare_optical

    store = Projects(data / "projects.sqlite3")
    project = store.get(identifier)
    report = asyncio.run(prepare_optical(StackRequest(**project["recipe"]), data))
    store.attach(identifier, project["revision"], report)
    print(
        {
            "project": project["name"],
            "revision": project["revision"],
            "run": report["id"],
            "summary": report["summary"],
            "acquisition": report["acquisition"],
        }
    )
    print(f"Artifacts: {(data / 'runs' / report['id']).resolve()}")


@app.command()
def sr_fetch(model_dir: Path = Path("data/models/sen2sr-lite-rgbn-x4")):
    """Explicitly download and verify pinned SEN2SRLite safetensors (~3.4 MB)."""
    from rslib.superresolution import fetch_weights

    typer.echo(json.dumps(fetch_weights(model_dir), indent=2))


@app.command()
def superresolve(
    source: Path,
    output: Path = Path("data/superresolution/output.tif"),
    model_dir: Path = Path("data/models/sen2sr-lite-rgbn-x4"),
    device: str = "cpu",
    precision: str = "float32",
):
    """SR of a cloud-masked, physical-reflectance 10 m R,G,B,NIR GeoTIFF.

    Requires the sr extra and sr-fetch. Output is a model-derived 2.5 m pixel grid,
    not a new measurement. Input band order, calibration and QA are caller duties.
    """
    import hashlib
    import time

    import numpy as np
    import rasterio

    from rslib.raster import Grid, write_cog
    from rslib.superresolution import load_sen2sr_lite, model_card, superresolve_rgbn, upscale_grid

    if source.resolve() == output.resolve():
        raise typer.BadParameter("Output must differ from the input")
    with rasterio.open(source) as src:
        if (
            src.count != 4
            or not src.crs
            or not src.crs.is_projected
            or src.crs.linear_units != "metre"
        ):
            raise typer.BadParameter("Input must be four-band R,G,B,NIR on a projected metric grid")
        if not np.allclose(
            [src.transform.a, src.transform.b, src.transform.d, src.transform.e], [10, 0, 0, -10]
        ):
            raise typer.BadParameter("This model requires an unrotated native 10 m grid")
        grid = Grid(src.crs.to_string(), src.transform, src.width, src.height)
        target = upscale_grid(grid)  # enforce output budget before raster/model allocation
        values = src.read(out_dtype="float32", masked=True).filled(np.nan)
        values = values * np.array(src.scales)[:, None, None] + np.array(src.offsets)[:, None, None]
    model = load_sen2sr_lite(model_dir, device)
    start = time.perf_counter()
    result = superresolve_rgbn(model, values, device=device, precision=precision)
    seconds = time.perf_counter() - start
    write_cog(output, result, target)
    manifest = {
        "schema_version": "rslib-superresolution/1",
        "model": model_card(),
        "input": {
            "path": str(source),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "grid": grid.metadata(),
        },
        "output": {
            "path": str(output),
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "grid": target.metadata(),
        },
        "device": device,
        "precision": precision,
        "fft_precision": "float32",
        "elapsed_inference_seconds": seconds,
        "mask": "Input NaNs restored on upscaled grid; no cloud reconstruction",
        "halo_input_pixels": 16,
        "accuracy": "Not evaluated against HR ground truth; model-derived detail",
    }
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    print(f"Model-derived RGBN COG: {output} · {seconds:.3f} s · nominal 2.5 m grid")


@app.command()
def doctor():
    """Show installed geospatial and native-kernel capabilities."""
    import importlib.util

    import rasterio

    from rslib.hydro import kernel_path

    print(
        {
            "rasterio": rasterio.__version__,
            "gdal": rasterio.__gdal_version__,
            "ml": bool(importlib.util.find_spec("sklearn")),
            "deep": bool(importlib.util.find_spec("torch")),
            "lazy_cube": bool(importlib.util.find_spec("odc")),
            "browser_built": (Path(__file__).parent / "web" / "index.html").is_file(),
        }
    )
    try:
        print(f"Rust kernel: {kernel_path()}")
    except RuntimeError as exc:
        print(str(exc))


if __name__ == "__main__":
    app()
