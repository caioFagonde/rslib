import "./workflows.css";
import { OpticalMap, type Boundary, type Bounds } from "./optical-map";
import type { FeatureCollection } from "geojson";

type Stats = { mean: number | null; valid_fraction: number };
type Frame = {
  day: string;
  image_url: string;
  support_url: string;
  observed_fraction: number;
  filled_fraction: number;
  statistics: Stats;
  map_image_url?: string;
  map_support_url?: string;
};
type Acquisition = {
  index?: number;
  id: string;
  platform: string;
  datetime: string;
};
type Source = Acquisition & { clear_fraction: number; cache_hit: boolean };
type Recipe = {
  demo: boolean;
  bbox: { west: number; south: number; east: number; north: number };
  datetime: string;
  sensors: string[];
  resolution: number;
  step_days: number;
  max_gap_days: number;
  cloud_buffer_m: number;
  min_clear_fraction: number;
  max_scenes_per_sensor: number;
  max_cloud: number;
  index: string;
  refresh: boolean;
  fields?: Boundary[];
  coverage_target?: number | null;
};
type Report = {
  id: string;
  synthetic: boolean;
  request: Recipe;
  elapsed_seconds: number;
  before_url: string;
  preview_url: string;
  cog_url: string;
  stack_url: string;
  series_url: string;
  support_cog_url?: string;
  composite_url: string;
  provenance_url: string;
  manifest_url: string;
  fields?: AreaSeries[];
  fields_csv_url?: string;
  fields_geojson_url?: string;
  display?: { bounds: Bounds; composite_url: string };
  acquisition?: {
    target_supported_fraction: number | null;
    stop_reason: string;
    steps: { observations: number; supported_fraction: number }[];
    unread_candidates: number;
  };
  timings?: {
    total_seconds: number;
    catalog_seconds: number;
    processing_export_seconds: number;
  };
  timeline: Frame[];
  observations: Source[];
  grid: { crs: string; width: number; height: number };
  coverage_notes: string[];
  summary: {
    observations: number;
    daily_mosaics: number;
    regular_dates: number;
    platforms: string[];
    cache_hits: number;
    observed_fraction: number;
    filled_fraction: number;
    unsupported_fraction: number;
  };
};
type Sample = {
  day: string;
  value: number | null;
  support: number;
  left_source: Acquisition | null;
  right_source: Acquisition | null;
  bracket_days: number | null;
};
type Pixel = {
  run_id: string;
  row: number;
  col: number;
  longitude: number;
  latitude: number;
  index: string;
  units: string;
  synthetic: boolean;
  series: Sample[];
};

type AreaFrame = {
  day: string;
  observed_mean: number | null;
  supported_mean: number | null;
  fixed_observed_mean: number | null;
  observed_fraction: number;
  estimated_fraction: number;
  missing_fraction: number;
  observed_area_m2: number;
  estimated_area_m2: number;
  missing_area_m2: number;
};
type AreaSeries = {
  id: string;
  name: string;
  area_m2: number;
  fixed_observed_area_m2: number;
  fixed_observed_fraction: number;
  area_crs: string;
  timeline: AreaFrame[];
};
type Project = {
  id: string;
  name: string;
  revision: number;
  recipe: Recipe;
  runs: {
    id: string;
    created: string;
    recipe_revision: number;
    synthetic: boolean;
    summary: Report["summary"];
  }[];
};

type JobEvent = {
  sequence: number;
  attempt: number;
  created: string;
  phase: string;
  message: string;
  source_id?: string;
  cache_hit?: boolean;
  clear_fraction?: number;
  supported_fraction?: number;
  observed_fraction?: number;
};
type Job = {
  kind: "optical" | "spectral";
  id: string;
  status: string;
  attempt: number;
  project_id: string | null;
  recipe_revision: number | null;
  recipe: Recipe;
  inventory_count: number;
  progress: { phase: string; message: string; source_id?: string };
  error: { code: string; message: string } | null;
  manifest_url: string | null;
};
let activeJob: Job | undefined,
  watchVersion = 0;
const $ = <T extends HTMLElement = HTMLElement>(id: string) =>
  document.getElementById(id) as T;
let report: Report | undefined, pixel: Pixel | undefined;
let support = false,
  position = 0,
  running = false,
  inspection = 0;
let boundaries: Boundary[] = [],
  project: Project | undefined,
  map: OpticalMap | undefined,
  importedInterval: string | undefined;
const kinds = ["Missing", "Observed daily mosaic", "Linear estimate"];
$("workflow-app").innerHTML = `
<header><a class="brand" href="/">RSLIB <span>Optical analysis</span></a><nav><a href="/">Scene explorer</a><a href="/showcase/">Development captures</a><a href="/showcase/research.html">Research methods</a><a href="/docs">API</a></nav></header>
<div class="layout"><aside><h1>Monitoring project</h1><label>Saved projects<select id="project-select"><option value="">Unsaved workspace</option></select></label><div class="pair project-actions"><button id="new-project" type="button">New project</button><button id="save-project" type="button">Save project</button></div><label>Project name<input id="project-name" value="Untitled optical project" maxlength="160" required></label><div id="project-state" class="note">Saved locally on this server.</div>
<details open class="boundary-panel"><summary>Monitoring areas <span id="boundary-count">0</span></summary><p class="note">Draw a polygon on the map or import WGS84 GeoJSON.</p><label>New area name<input id="boundary-name" value="Area 1" maxlength="160"></label><div class="pair"><button id="draw-area" type="button">Draw polygon</button><button id="import-areas" type="button">Import GeoJSON</button></div><input id="areas-file" type="file" accept="application/geo+json,application/json,.json,.geojson" hidden><div id="boundary-list"></div></details><details id="preparation-settings" open><summary>Acquisition and processing</summary>
<form id="recipe"><fieldset id="controls">
<label>Data source<select id="source"><option value="live">Satellite catalogs</option><option value="demo">Synthetic test data · Itatiaia only</option></select></label>
<div class="sensor-options"><label><input id="sentinel" type="checkbox" checked> Sentinel-2</label><label><input id="landsat" type="checkbox" checked> Landsat 8/9</label></div>
<label>Bounding box <small>Longitude / latitude: west, south, east, north</small><input id="bbox" value="-44.66,-22.41,-44.64,-22.39" required></label>
<div class="pair"><label>Start date<input id="start" type="date" value="2026-06-01" required></label><label>End date<input id="end" type="date" value="2026-07-16" required></label></div>
<div class="pair"><label>Grid spacing (m)<input id="resolution" type="number" min="30" max="1000" value="30" required></label><label>Interval (days)<input id="step" type="number" min="1" max="365" value="5" required></label></div>
<div class="pair"><label>Max. bracket (days)<input id="gap" type="number" min="1" max="90" value="20" required></label><label>Cloud buffer (m)<input id="buffer" type="number" min="0" max="1000" value="60" required></label></div>
<div class="pair"><label>Index<select id="index"><option value="ndvi">NDVI</option><option value="ndmi">NDMI</option><option value="nbr">NBR</option><option value="evi">EVI</option></select></label><label>Scene budget / sensor<input id="limit" type="number" min="1" max="12" value="4" required></label></div>
<div class="pair"><label>Scene cloud ≤ (%)<input id="cloud" type="number" min="0" max="100" value="40" required></label><label>Clear support ≥ (%)<input id="clear" type="number" min="1" max="100" value="90" required></label></div>
<label class="check"><input id="coverage-auto" type="checkbox" checked> Acquire toward a coverage goal</label><label>Supported pixel dates ≥ (%)<input id="coverage-goal" type="number" min="1" max="100" value="80" required><small>Includes permitted estimates. Stops at the scene budget.</small></label><label class="check"><input id="refresh" type="checkbox"> Rebuild cached scene preparations</label>
<button id="run" type="submit" class="primary">Run preparation</button>
<div class="recipe-actions"><button id="save-recipe" type="button">Save recipe</button><button id="load-recipe" type="button">Load recipe</button><input id="recipe-file" type="file" accept="application/json,.json" hidden></div>
</fieldset></form></details><div id="status" role="status">No run loaded.</div>
<details><summary>Methods and limits</summary><p>Native cloud, shadow and snow masks are buffered before area averaging. A cell requires the chosen clear support in every band and a clear center.</p><p>The common NIR band uses Sentinel B8A and Landsat B05. MSI-to-OLI bandpass coefficients provide partial harmonization. Atmospheric reprocessing, BRDF normalization and image registration are not applied.</p><p>Filling uses linear interpolation between clear daily mosaics. The whole bracket must fit the maximum gap. Edges and longer gaps remain missing. Filling can obscure abrupt change. Use the reconstruction check below to withhold complete acquisition days and measure error on clear reference cells.</p><p>Jobs retain their recipe and selected scenes across reloads and server restarts. Cancellation takes effect between processing checkpoints; an active GDAL read finishes first. Retries reuse completed scene preparations.</p></details></aside>
<main><div class="heading"><div><h2 id="workspace-title">Optical monitoring</h2><p id="run-info">Choose an area and dates, then run preparation.</p></div><div class="heading-actions"><span id="mode" class="badge">NO DATA</span><button id="workspace-run" type="button" class="primary">Run preparation</button></div></div><div id="workspace-status" role="status" hidden></div>
<section id="job-panel" class="job-panel" hidden aria-label="Preparation job">
<div class="job-heading"><div><h3 id="job-title">Preparation job</h3><p id="job-detail"></p></div><div class="job-actions"><button id="job-cancel" type="button" hidden>Cancel job</button><button id="job-retry" type="button" hidden>Retry saved job</button><button id="job-reconnect" type="button" hidden>Reconnect</button><button id="job-copy" type="button">Copy job link</button></div></div>
<p id="job-progress" role="status"></p><p id="job-coverage" class="note"></p><details id="job-journal"><summary>Processing journal</summary><ol id="job-events"></ol></details>
</section><details id="jobs-history"><summary>Recent processing jobs</summary><div id="job-list"></div></details>
<section class="map-workspace"><div class="map-tools"><span id="map-date">No run</span><button id="fit-area" type="button">Fit acquisition area</button><label>Mode<select id="map-interaction"><option value="area">Select areas</option><option value="cell">Inspect cells</option></select></label><label>Layer<select id="map-layer"><option value="index">Selected date</option><option value="support">Temporal support</option><option value="composite">Latest clear composite</option><option value="none">Boundaries only</option></select></label><label class="opacity-label">Opacity<input id="map-opacity" type="range" min="0" max="100" value="85"></label><label class="check"><input id="map-base" type="checkbox" checked>Base map</label><button id="finish-area" type="button" hidden>Finish polygon</button><button id="cancel-area" type="button" hidden>Cancel</button></div><div id="optical-map" aria-label="Interactive optical monitoring map"></div><div class="map-caption"><span id="map-message">Select an area or inspect a cell. Scroll to zoom; drag to pan.</span><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a></div></section>
<div id="empty"><h3>No observations loaded</h3><p>Satellite catalogs require network access. You can also run a small synthetic fixture to examine the processing and exports.</p><button id="example" type="button">Run synthetic example</button></div>
<div id="results" hidden>
<section class="coverage-panel" aria-label="Support across the requested area and dates"><div class="coverage-title"><h3>Coverage of requested pixel dates</h3><strong id="missing-total"></strong></div><div id="coverage-bar" class="coverage-bar"></div><div id="coverage-numbers" class="legend"></div><p id="coverage-notes" class="note"></p></section>
<div class="view-toolbar"><span id="grid"></span><span id="index-label"></span></div>
<details id="raster-comparison"><summary>Raster comparison and row/column inspection</summary><section class="image-grid"><figure><figcaption><strong>Selected date <span id="frame-date"></span></strong><button id="support-toggle" type="button" aria-pressed="false">Show support</button></figcaption><div class="raster"><img id="frame" alt="Selected date; click to inspect a common-grid cell"><span class="crosshair" hidden></span></div><div class="raster-footer"><span id="fractions"></span><span>Click a cell to inspect</span></div></figure>
<figure><figcaption><strong>Latest clear composite</strong><span>Dates vary by cell</span></figcaption><div class="raster"><img id="composite" alt="Latest clear composite; click to inspect a common-grid cell"><span class="crosshair" hidden></span></div><div class="raster-footer">A complete observed spectrum per cell. Source indices are in the provenance export.</div></figure></section></details>
<div class="raster-legend"><div><span id="colorbar-name">Index display</span><span class="index-ramp"></span><span>−1</span><span>0</span><span>+1</span></div><p>Shared color scale, clipped to [−1, +1] for display. Exported values retain their range. Checkerboard: missing.</p><p id="support-legend" hidden><i class="support-observed"></i>Observed <i class="support-estimated"></i>Estimated <i class="support-missing"></i>Missing · support view applies to the selected date.</p></div>
<section class="timeline"><div class="section-title"><div><h3 id="chart-title">AOI mean</h3><div class="chart-controls"><label>Area<select id="series-scope"><option value="aoi">Acquisition AOI</option><option value="pixel" disabled>Selected cell</option></select></label><label id="area-metric-label" hidden>Statistic<select id="area-metric"><option value="observed_mean">Observed area mean</option><option value="supported_mean">Observed + estimated mean</option><option value="fixed_observed_mean">Fixed observed footprint</option></select></label></div></div><button id="clear-pixel" type="button" hidden>Return to AOI mean</button></div><input id="date-slider" type="range" min="0" max="0" value="0" aria-label="Select time-series date"><div id="chart"></div><p id="chart-note" class="note">Mean of valid AOI pixels; changing coverage changes the population. This is not a fixed-sample trend estimate.</p></section>
<section id="field-statistics" hidden><div class="section-title"><h3>Monitoring areas · selected date</h3><a id="fields-csv" download>Download area series CSV</a></div><div class="table-scroll"><table><thead><tr><th>Area</th><th>Size / ha</th><th>Observed</th><th>Estimated</th><th>Missing</th><th>Observed mean</th></tr></thead><tbody id="field-rows"></tbody></table></div><div id="area-detail" class="note"></div><div id="area-date-table" class="table-scroll"><table><thead><tr><th>Date / UTC</th><th>Observed area</th><th>Estimated area</th><th>Missing area</th><th>Observed mean</th><th>Supported mean</th></tr></thead><tbody id="field-dates"></tbody></table></div></section>
<section class="agreement-panel"><div class="section-title"><h3>Observed-scene spectral analysis</h3><a id="spectral-launch" href="/spectral.html">Analyze observed spectra</a></div><p class="note">Fit PCA, select VCA endmembers, inspect constrained fractions and export a reproducible report. Fits use one acquired scene; fractions have no independent material validation.</p><div id="spectral-history" class="exports"></div></section>
<section class="agreement-panel"><div class="section-title"><h3>Cross-sensor agreement</h3><button id="compare-sensors" type="button">Compare Landsat / Sentinel</button></div><p class="note">Closest-time disjoint acquisition pairs, using common clear complete spectra on the analysis grid. Differences are Sentinel-2 minus Landsat; neither sensor is treated as ground truth.</p><div class="agreement-controls"><label>Maximum separation / hours<input id="agreement-hours" type="number" value="48" min="1" max="168" step="0.1"></label><label>Minimum common clear cells<input id="agreement-cells" type="number" value="100" min="1" max="1048576"></label></div><div id="agreement-result" aria-live="polite"></div></section>
<section class="validation-panel"><div class="section-title"><h3>Gap-filling evaluation</h3><button id="validate-series" type="button">Withhold acquisition days</button></div><p class="note">Remove one complete UTC day at a time, including every sensor on that day. Predict its clear cells from the remaining dates. Compare linear interpolation with the nearest bracket observation on the same cells and bracket limit.</p><div id="validation-result" aria-live="polite"></div></section>
<section class="pixel-panel"><div class="section-title"><h3>Cell inspector</h3><button id="pixel-csv" type="button" disabled>Download cell CSV</button></div><form id="cell-form"><label>Row<input id="cell-row" type="number" min="0" value="0" required></label><label>Column<input id="cell-col" type="number" min="0" value="0" required></label><button type="submit">Inspect</button><span id="cell-location">Select a cell in either raster. Row and column are zero based.</span></form><div id="pixel-detail" aria-live="polite"></div></section>
<details class="sources-panel" open><summary>Acquisitions and exports</summary><div class="bottom-grid"><section><div class="table-scroll"><table><thead><tr><th>Acquisition / UTC</th><th>Platform</th><th>Clear AOI</th><th>Scene ID</th></tr></thead><tbody id="sources"></tbody></table></div><figure class="first-observation"><img id="before" alt="First observed UTC day"><figcaption>First observed day · gaps remain masked</figcaption></figure></section><section><h3>Downloads</h3><div id="exports" class="exports"></div><p id="interpretation" class="note"></p></section></div></details>
</div><section id="project-history" hidden><h3>Project runs</h3><div id="run-history"></div></section></main></div>`;

function input(id: string) {
  return $<HTMLInputElement>(id).value;
}
function checked(id: string) {
  return $<HTMLInputElement>(id).checked;
}
function fraction(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}
function download(name: string, body: string, type: string) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function recipe(): Recipe {
  const coords = input("bbox").split(",").map(Number);
  if (coords.length !== 4 || !coords.every(Number.isFinite))
    throw new Error(
      "Enter four bounding-box coordinates: west, south, east, north.",
    );
  return {
    demo: input("source") === "demo",
    bbox: {
      west: coords[0],
      south: coords[1],
      east: coords[2],
      north: coords[3],
    },
    datetime: importedInterval ?? `${input("start")}/${input("end")}`,
    sensors: [
      ...(checked("sentinel") ? ["sentinel-2"] : []),
      ...(checked("landsat") ? ["landsat"] : []),
    ],
    resolution: Number(input("resolution")),
    step_days: Number(input("step")),
    max_gap_days: Number(input("gap")),
    cloud_buffer_m: Number(input("buffer")),
    min_clear_fraction: Number(input("clear")) / 100,
    max_scenes_per_sensor: Number(input("limit")),
    max_cloud: Number(input("cloud")),
    index: input("index"),
    refresh: checked("refresh"),
    fields: boundaries,
    coverage_target: checked("coverage-auto")
      ? Number(input("coverage-goal")) / 100
      : null,
  };
}
function setRecipe(r: Recipe) {
  if (!r.bbox || !r.datetime || !Array.isArray(r.sensors))
    throw new Error("Expected an optical StackRequest JSON recipe.");
  const values: Record<string, string | number> = {
    source: r.demo ? "demo" : "live",
    bbox: [r.bbox.west, r.bbox.south, r.bbox.east, r.bbox.north].join(","),
    start: r.datetime.split("/")[0].slice(0, 10),
    end: r.datetime.split("/")[1]?.slice(0, 10),
    resolution: r.resolution,
    step: r.step_days,
    gap: r.max_gap_days,
    buffer: r.cloud_buffer_m,
    clear: r.min_clear_fraction * 100,
    limit: r.max_scenes_per_sensor,
    cloud: r.max_cloud,
    index: r.index,
  };
  for (const [key, value] of Object.entries(values))
    $<HTMLInputElement>(key).value = String(value);
  $<HTMLInputElement>("sentinel").checked = r.sensors.includes("sentinel-2");
  $<HTMLInputElement>("landsat").checked = r.sensors.includes("landsat");
  $<HTMLInputElement>("refresh").checked = Boolean(r.refresh);
  $<HTMLInputElement>("coverage-auto").checked = r.coverage_target != null;
  $<HTMLInputElement>("coverage-goal").value = String(
    (r.coverage_target ?? 0.8) * 100,
  );
  boundaries = r.fields ?? [];
  importedInterval = r.datetime;
  renderBoundaries();
}
function showFrame() {
  if (!report) return;
  $("support-legend").hidden = !support;
  const f = report.timeline[position];
  $<HTMLImageElement>("frame").src = support ? f.support_url : f.image_url;
  $("frame-date").textContent = f.day;
  $("fractions").textContent =
    `${fraction(f.observed_fraction)} observed · ${fraction(f.filled_fraction)} estimated · ${fraction(Math.max(0, 1 - f.observed_fraction - f.filled_fraction))} missing`;
  const detail = $("pixel-detail");
  detail.replaceChildren();
  if (pixel) {
    const s = pixel.series[position];
    const facts = document.createElement("p");
    facts.className = "sample-value";
    facts.textContent = `${s.day} · ${s.value === null ? "No value" : s.value.toFixed(4)} · ${kinds[s.support]}`;
    detail.append(facts);
    if (s.support === 2) {
      const p = document.createElement("p");
      p.textContent = `Bracket: ${s.bracket_days?.toFixed(1)} days. Value is a temporal estimate; no uncertainty calibration is available.`;
      detail.append(p);
    }
    const sources =
      s.left_source?.index === s.right_source?.index
        ? [s.left_source]
        : [s.left_source, s.right_source];
    sources
      .filter((o): o is Acquisition => o !== null)
      .forEach((o, i) => {
        const p = document.createElement("p");
        p.className = "source-reference";
        p.textContent = `${s.support === 2 ? (i === 0 ? "Left" : "Right") : "Source"}: ${o.datetime} · ${o.platform} · ${o.id}`;
        detail.append(p);
      });
    if (s.support === 0) {
      const p = document.createElement("p");
      p.textContent =
        "No accepted observation or permitted interpolation on this date.";
      detail.append(p);
    }
  }
  chart();
  renderAreaStatistics();
  renderMap();
}
function selectedArea() {
  const scope = input("series-scope");
  return report?.fields?.find((f) => "field:" + f.id === scope);
}
function chart() {
  if (!report) return;
  const field = selectedArea(),
    metric = input("area-metric") as
      | "observed_mean"
      | "supported_mean"
      | "fixed_observed_mean";
  $("area-metric-label").hidden = !field;
  const data = report.timeline.map((f, i) => ({
    day: f.day,
    value: pixel
      ? pixel.series[i].value
      : field
        ? field.timeline[i][metric]
        : f.statistics.mean,
    kind: pixel
      ? pixel.series[i].support
      : field &&
          metric === "supported_mean" &&
          field.timeline[i].estimated_fraction > 0
        ? 2
        : 1,
  }));
  $("chart-title").textContent = pixel
    ? `${report.request.index.toUpperCase()} · cell ${pixel.row}, ${pixel.col}`
    : field
      ? `${report.request.index.toUpperCase()} · ${field.name}`
      : `${report.request.index.toUpperCase()} · acquisition AOI`;
  $("chart-note").textContent = pixel
    ? "Filled circles: observed daily mosaic. Open diamonds: linear estimates. Missing dates have no marker. Source acquisitions appear in the cell inspector."
    : field
      ? metric === "fixed_observed_mean"
        ? `Same observed cells on every requested date: ${(field.fixed_observed_area_m2 / 10000).toFixed(2)} ha (${fraction(field.fixed_observed_fraction)} of area). A null curve means no common observed footprint.`
        : metric === "observed_mean"
          ? "Area-weighted mean of observed cells only. Coverage can change between dates; use Fixed observed footprint for a constant spatial sample."
          : "Area-weighted mean including permitted temporal estimates. Open diamonds indicate dates with estimated area; this is not an observed-only trend."
      : "Mean of valid AOI cells; changing coverage changes the population. Select a monitoring area for fractional-cell area statistics.";
  const ns = "http://www.w3.org/2000/svg",
    svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 900 190");
  svg.setAttribute("role", "img");
  svg.setAttribute(
    "aria-label",
    `${report.request.index.toUpperCase()} time series, dimensionless, UTC dates`,
  );
  function node(
    tag: string,
    attrs: Record<string, string | number>,
    content?: string,
  ) {
    const el = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
    if (content !== undefined) el.textContent = content;
    svg.append(el);
    return el;
  }
  const valid = data.map((f) => f.value).filter((v): v is number => v !== null),
    lo = Math.min(...valid, 0),
    hi = Math.max(...valid, 0.2) + 0.05;
  const first = Date.parse(data[0].day),
    last = Date.parse(data[data.length - 1].day);
  const x = (day: string) =>
      55 + ((Date.parse(day) - first) * 820) / Math.max(86400000, last - first),
    y = (v: number) => 143 - ((v - lo) / (hi - lo)) * 110;
  for (let k = 0; k < 4; k++) {
    const v = lo + ((hi - lo) * k) / 3;
    node("line", { x1: 55, x2: 875, y1: y(v), y2: y(v), stroke: "#dce2e8" });
    node(
      "text",
      {
        x: 44,
        y: y(v) + 4,
        "text-anchor": "end",
        fill: "#526172",
        "font-size": 11,
      },
      v.toFixed(2),
    );
  }
  node(
    "text",
    { x: 55, y: 15, fill: "#526172", "font-size": 11 },
    `${report.request.index.toUpperCase()} (unitless)`,
  );
  const ticks = new Set([
    0,
    Math.floor((data.length - 1) / 3),
    Math.floor((2 * (data.length - 1)) / 3),
    data.length - 1,
  ]);
  for (const i of ticks)
    node(
      "text",
      {
        x: x(data[i].day),
        y: 173,
        "text-anchor":
          i === 0 ? "start" : i === data.length - 1 ? "end" : "middle",
        fill: "#526172",
        "font-size": 11,
      },
      data[i].day,
    );
  node("line", {
    x1: x(data[position].day),
    x2: x(data[position].day),
    y1: 25,
    y2: 150,
    stroke: "#617387",
    "stroke-dasharray": "3 3",
  });
  if (!valid.length)
    node(
      "text",
      {
        x: 465,
        y: 88,
        "text-anchor": "middle",
        fill: "#526172",
        "font-size": 13,
      },
      "No values for this statistic and date range",
    );
  data.forEach((f, i) => {
    if (f.value === null) return;
    const prev = data[i - 1];
    if (prev?.value !== null && prev?.value !== undefined)
      node("line", {
        x1: x(prev.day),
        x2: x(f.day),
        y1: y(prev.value),
        y2: y(f.value),
        stroke: "#335e84",
        "stroke-width": 1.5,
        "stroke-dasharray": prev.kind === 2 || f.kind === 2 ? "5 4" : "",
      });
    const cx = x(f.day),
      cy = y(f.value),
      estimated = f.kind === 2;
    const dot = estimated
      ? node("path", {
          d: `M${cx},${cy - 5}l5,5 -5,5 -5,-5Z`,
          fill: "#fff",
          stroke: "#996300",
          "stroke-width": 2,
        })
      : node("circle", { cx, cy, r: 4, fill: "#276c53" });
    dot.setAttribute("tabindex", "0");
    dot.setAttribute("role", "button");
    dot.setAttribute("aria-label", `${f.day}: ${f.value.toFixed(4)}`);
    dot.addEventListener("click", () => selectDate(i));
    dot.addEventListener("keydown", (e) => {
      if ((e as KeyboardEvent).key === "Enter") selectDate(i);
    });
    const title = document.createElementNS(ns, "title");
    title.textContent = `${f.day}: ${f.value.toFixed(4)}`;
    dot.append(title);
  });
  $("chart").replaceChildren(svg);
}
function selectDate(i: number) {
  position = i;
  $<HTMLInputElement>("date-slider").value = String(i);
  showFrame();
}
function clearPixel() {
  inspection++;
  pixel = undefined;
  $<HTMLOptionElement>("series-scope").querySelector<HTMLOptionElement>(
    "option[value=pixel]",
  )!.disabled = true;
  if (input("series-scope") === "pixel")
    $<HTMLSelectElement>("series-scope").value = "aoi";
  $("clear-pixel").hidden = true;
  $<HTMLButtonElement>("pixel-csv").disabled = true;
  document
    .querySelectorAll<HTMLElement>(".crosshair")
    .forEach((el) => (el.hidden = true));
  $("cell-location").textContent =
    "Select a cell in either raster. Row and column are zero based.";
  $("pixel-detail").replaceChildren();
}
async function inspect(row: number, col: number) {
  return inspectQuery(`row=${row}&col=${col}`);
}
async function inspectQuery(query: string) {
  if (!report) return;
  const token = ++inspection,
    id = report.id;
  $("cell-location").textContent = "Reading cell values…";
  try {
    const response = await fetch(`/api/runs/${id}/pixel?${query}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail);
    if (token !== inspection || report.id !== id) return;
    pixel = result as Pixel;
    const row = pixel.row,
      col = pixel.col;
    $<HTMLSelectElement>("series-scope").value = "pixel";
    $<HTMLOptionElement>("series-scope").querySelector<HTMLOptionElement>(
      "option[value=pixel]",
    )!.disabled = false;
    $<HTMLSelectElement>("series-scope").value = "pixel";
    $("cell-location").textContent =
      `${pixel.longitude.toFixed(6)}°, ${pixel.latitude.toFixed(6)}° · ${report.grid.crs}`;
    $<HTMLInputElement>("cell-row").value = String(row);
    $<HTMLInputElement>("cell-col").value = String(col);
    $("clear-pixel").hidden = false;
    $<HTMLButtonElement>("pixel-csv").disabled = false;
    document.querySelectorAll<HTMLElement>(".crosshair").forEach((el) => {
      el.hidden = false;
      el.style.left = `${((col + 0.5) / report!.grid.width) * 100}%`;
      el.style.top = `${((row + 0.5) / report!.grid.height) * 100}%`;
    });
    showFrame();
  } catch (error) {
    if (token === inspection)
      $("cell-location").textContent = String(
        error instanceof Error ? error.message : error,
      );
  }
}
function render() {
  if (!report) return;
  const r = report,
    s = r.summary;
  $("agreement-result").replaceChildren();
  $<HTMLButtonElement>("compare-sensors").disabled = false;
  $("validation-result").replaceChildren();
  $<HTMLButtonElement>("validate-series").disabled = false;
  clearPixel();
  renderScopes();
  $("empty").hidden = true;
  $("results").hidden = false;
  $("mode").textContent = r.synthetic
    ? "SYNTHETIC TEST DATA"
    : "SATELLITE OBSERVATIONS";
  $("mode").dataset.synthetic = String(r.synthetic);
  $("run-info").textContent =
    `${s.observations} scenes · ${s.daily_mosaics} acquisition days · ${s.regular_dates} requested dates · ${s.cache_hits} scenes reused · workflow total ${r.timings?.total_seconds.toFixed(2) ?? "—"} s · catalog ${r.timings?.catalog_seconds.toFixed(2) ?? "—"} s · processing/export ${r.elapsed_seconds.toFixed(2)} s`;
  $("missing-total").textContent =
    `${fraction(s.unsupported_fraction)} missing`;
  const bar = $("coverage-bar"),
    numbers = $("coverage-numbers");
  bar.replaceChildren();
  numbers.replaceChildren();
  for (const [label, value, kind] of [
    ["Observed", s.observed_fraction, "observed"],
    ["Estimated", s.filled_fraction, "filled"],
    ["Missing", s.unsupported_fraction, "missing"],
  ] as const) {
    const segment = document.createElement("span");
    segment.className = kind;
    segment.style.width = `${value * 100}%`;
    bar.append(segment);
    const text = document.createElement("span");
    text.className = kind + "-text";
    text.textContent = `${label}: ${fraction(value)}`;
    numbers.append(text);
  }
  $("coverage-notes").textContent =
    (r.coverage_notes.length
      ? r.coverage_notes.join(" ")
      : "Coverage counts accepted observations and permitted estimates. It does not measure interpolation accuracy.") +
    " Fractions include every AOI cell on every requested date." +
    (r.acquisition?.target_supported_fraction != null
      ? ` Acquisition: ${r.acquisition.stop_reason.replaceAll("_", " ")} after ${r.acquisition.steps.length} coverage checks.`
      : "");
  $("grid").textContent =
    `${r.grid.crs} · ${r.grid.width} × ${r.grid.height} cells · ${r.request.resolution} m`;
  $("index-label").textContent = `${r.request.index.toUpperCase()} · unitless`;
  $("colorbar-name").textContent = r.request.index.toUpperCase();
  document
    .querySelectorAll<HTMLElement>(".raster")
    .forEach((el) =>
      el.style.setProperty("--ratio", `${r.grid.width}/${r.grid.height}`),
    );
  $<HTMLImageElement>("before").src = r.before_url;
  $<HTMLImageElement>("composite").src = r.preview_url;
  $<HTMLInputElement>("date-slider").max = String(r.timeline.length - 1);
  $<HTMLInputElement>("cell-row").max = String(r.grid.height - 1);
  $<HTMLInputElement>("cell-col").max = String(r.grid.width - 1);
  position = Math.min(position, r.timeline.length - 1);
  $<HTMLInputElement>("date-slider").value = String(position);
  $("sources").replaceChildren(
    ...r.observations.map((o) => {
      const row = document.createElement("tr");
      for (const value of [
        o.datetime.replace("T", " ").replace("Z", ""),
        o.platform,
        fraction(o.clear_fraction),
        o.id,
      ]) {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.append(cell);
      }
      return row;
    }),
  );
  const links = [
    ["Run observed-scene spectral analysis", `/spectral.html?run=${r.id}`],
    ["Index time series · COG", r.cog_url],
    ["Reflectance stack · NPZ", r.stack_url],
    ["Time series and support · NPZ", r.series_url],
    ["Latest clear reflectance · COG", r.composite_url],
    ["Composite provenance · COG", r.provenance_url],
    ["Recipe, sources and checksums · JSON", r.manifest_url],
  ];
  if (r.fields_csv_url && r.fields?.length)
    links.push(
      ["Monitoring area series · CSV", r.fields_csv_url],
      ["Area boundaries · GeoJSON", r.fields_geojson_url!],
    );
  if (r.support_cog_url)
    links.splice(3, 0, ["Time series support · COG", r.support_cog_url]);
  $("exports").replaceChildren(
    ...links.map(([label, href]) => {
      const a = document.createElement("a");
      a.href = href;
      a.textContent = label;
      if (href.startsWith("/api/")) a.setAttribute("download", "");
      return a;
    }),
  );
  $<HTMLAnchorElement>("spectral-launch").href = `/spectral.html?run=${r.id}`;
  $("spectral-history").textContent = "Loading analyses of this run…";
  void api<{ jobs: Job[] }>(`/api/jobs?source_run_id=${r.id}`)
    .then(({ jobs }) => {
      if (report?.id !== r.id) return;
      $("spectral-history").replaceChildren(
        ...jobs.map((job) => {
          const a = document.createElement("a");
          a.href = `/spectral.html?job=${job.id}`;
          a.textContent = `${job.status} · ${job.id.slice(0, 8)} · attempt ${job.attempt}`;
          return a;
        }),
      );
      if (!jobs.length)
        $("spectral-history").textContent =
          "No spectral jobs for this run yet.";
    })
    .catch(() => {
      if (report?.id === r.id)
        $("spectral-history").textContent =
          "Spectral history unavailable. Reopen the analysis page to retry.";
    });
  $("interpretation").textContent = r.synthetic
    ? "All input observations in this run are synthetic. This example checks processing behavior; it provides no evidence of accuracy on satellite imagery."
    : "Sentinel-2 and Landsat surface reflectance with partial bandpass harmonization. Residual sensor, atmospheric and BRDF differences have not been quantified here.";
  showFrame();
  const url = new URL(location.href);
  url.searchParams.set("run", r.id);
  if (project) url.searchParams.set("project", project.id);
  history.replaceState(null, "", url);
}
function setBusy(busy: boolean) {
  running = busy;
  document
    .querySelectorAll<
      HTMLInputElement | HTMLSelectElement | HTMLButtonElement
    >("aside input, aside select, aside button, .map-tools button, #workspace-run")
    .forEach((el) => (el.disabled = busy));
  $<HTMLFieldSetElement>("controls").disabled = busy;
  $<HTMLButtonElement>("example").disabled = busy;
}
async function listJobs() {
  const result = await api<{ jobs: Job[] }>("/api/jobs");
  $("job-list").replaceChildren(
    ...result.jobs.map((job) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `${job.status} · ${job.kind === "spectral" ? "spectral analysis" : job.recipe.demo ? "synthetic" : "satellite"} · ${job.id.slice(0, 8)} · attempt ${job.attempt}${job.recipe_revision ? ` · revision ${job.recipe_revision}` : ""}`;
      button.onclick = () => void followJob(job.id, true);
      return button;
    }),
  );
}
function paintJob(job: Job, events: JobEvent[]) {
  activeJob = job;
  $("job-panel").hidden = false;
  $("job-title").textContent = `Preparation · ${job.status}`;
  $("job-detail").textContent =
    `${job.id} · attempt ${job.attempt} · ${job.inventory_count} saved candidates${job.recipe_revision ? ` · recipe revision ${job.recipe_revision}` : ""} · ${job.recipe.demo ? "Synthetic test data" : "Satellite data"}`;
  $("job-progress").textContent = job.error
    ? `${job.error.code}: ${job.error.message}`
    : job.progress.message;
  $("job-cancel").hidden = !["queued", "running", "cancelling"].includes(
    job.status,
  );
  $<HTMLButtonElement>("job-cancel").disabled = job.status === "cancelling";
  $("job-retry").hidden = !["cancelled", "failed"].includes(job.status);
  const coverage = [...events].reverse().find((e) => e.phase === "coverage");
  $("job-coverage").textContent = coverage
    ? `Last measured support: ${fraction(coverage.observed_fraction ?? 0)} observed, ${fraction((coverage.supported_fraction ?? 0) - (coverage.observed_fraction ?? 0))} estimated, ${fraction(1 - (coverage.supported_fraction ?? 0))} missing.`
    : "";
  $("job-events").replaceChildren(
    ...events.slice(-30).map((event) => {
      const row = document.createElement("li");
      const time = document.createElement("time");
      time.textContent = `${event.created.slice(11, 19)} UTC · ${event.attempt}`;
      const label = document.createElement("span");
      label.textContent = `${event.message}${event.phase === "prepared" ? ` · ${event.cache_hit ? "cached" : "read from source"} · ${fraction(event.clear_fraction ?? 0)} clear` : ""}`;
      row.append(time, label);
      return row;
    }),
  );
}
async function followJob(id: string, restore = false) {
  const version = ++watchVersion;
  let after = 0,
    events: JobEvent[] = [];
  setBusy(true);
  $("job-reconnect").hidden = true;
  const url = new URL(location.href);
  url.searchParams.set("job", id);
  history.replaceState(null, "", url);
  try {
    while (version === watchVersion) {
      const [job, journal] = await Promise.all([
        api<Job>(`/api/jobs/${id}`),
        api<{ events: JobEvent[] }>(`/api/jobs/${id}/events?after=${after}`),
      ]);
      if (version !== watchVersion) return;
      if (job.kind === "spectral") {
        location.href = `/spectral.html?job=${job.id}`;
        return;
      }
      if (restore) {
        project = job.project_id
          ? await api<Project>(`/api/projects/${job.project_id}`)
          : undefined;
        setRecipe(job.recipe);
        if (project) $<HTMLInputElement>("project-name").value = project.name;
        renderHistory();
        restore = false;
      }
      events.push(...journal.events);
      after = events.at(-1)?.sequence ?? after;
      paintJob(job, events);
      $("status").textContent = `${job.status}: ${job.progress.message}`;
      $("status").dataset.state = "running";
      // Drain the journal before final display, including recovered attempts.
      if (journal.events.length === 200) continue;
      if (["succeeded", "cancelled", "failed"].includes(job.status)) {
        while (true) {
          const tail = await api<{ events: JobEvent[] }>(
            `/api/jobs/${id}/events?after=${after}`,
          );
          if (version !== watchVersion) return;
          events.push(...tail.events);
          after = events.at(-1)?.sequence ?? after;
          if (tail.events.length < 200) break;
        }
        paintJob(job, events);
        if (job.manifest_url) {
          report = await api<Report>(job.manifest_url);
          render();
          if (project?.id === job.project_id) {
            project = await api<Project>(`/api/projects/${project.id}`);
            renderHistory();
          }
          map?.fit(currentBounds());
          $("status").textContent =
            `Outputs written. ${fraction(report.summary.unsupported_fraction)} of requested pixel dates have no value.`;
          $("status").dataset.state = "complete";
          $("status").dataset.coverage =
            report.summary.unsupported_fraction > 0 ? "partial" : "supported";
        } else {
          $("status").textContent =
            job.error?.message ??
            "Job cancelled. Completed scene preparations remain cached.";
          $("status").dataset.state =
            job.status === "failed" ? "error" : "cancelled";
        }
        await listJobs();
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 600));
    }
  } catch (error) {
    if (version === watchVersion) {
      $("status").textContent =
        `Connection interrupted: ${error instanceof Error ? error.message : String(error)}. The server retains this job; reconnect to check its state.`;
      $("status").dataset.state = "error";
      $("job-reconnect").hidden = false;
    }
  } finally {
    if (version === watchVersion) setBusy(false);
  }
}
async function run() {
  if (running) return;
  try {
    const body = recipe();
    setBusy(true);
    if (project) await saveProject();
    const job = await api<Job>("/api/jobs", {
      ...(project
        ? { project_id: project.id, revision: project.revision }
        : { recipe: body }),
      request_key: crypto.randomUUID(),
    });
    await followJob(job.id);
  } catch (error) {
    $("status").textContent =
      error instanceof Error ? error.message : String(error);
    $("status").dataset.state = "error";
    setBusy(false);
  }
}
$("job-cancel").onclick = async () => {
  if (activeJob) {
    try {
      await api(`/api/jobs/${activeJob.id}/cancel`, {});
      $<HTMLButtonElement>("job-cancel").disabled = true;
    } catch (error) {
      $("status").textContent = String(error);
    }
  }
};
$("job-retry").onclick = async () => {
  if (!activeJob) return;
  try {
    const job = await api<Job>(`/api/jobs/${activeJob.id}/retry`, {});
    await followJob(job.id, true);
  } catch (error) {
    $("status").textContent = String(error);
  }
};
$("job-reconnect").onclick = () => {
  const id = activeJob?.id ?? new URL(location.href).searchParams.get("job");
  if (id) void followJob(id, true);
};
$("job-copy").onclick = async () => {
  try {
    await navigator.clipboard.writeText(location.href);
  } catch {
    $("status").textContent = "Copy the job URL from the address bar.";
  }
};
type AgreementStats = {
  samples: number;
  bias: number;
  mae: number;
  rmse: number;
  correlation: number | null;
};
type AgreementBand = {
  band: string;
  current: AgreementStats;
  before_local_bandpass: AgreementStats | null;
  scatter: {
    reference: number[];
    current: number[];
    before_local_bandpass: number[] | null;
  };
};
type AgreementPair = {
  reference: Acquisition;
  comparison: Acquisition;
  separation_hours: number;
  common_clear_cells: number;
  common_clear_fraction: number;
  bands: AgreementBand[];
  ndvi: AgreementStats | null;
  spectral_angle: { median: number | null; p95: number | null };
  before_local_bandpass_available: boolean;
  scatter_cells: { rows: number[]; columns: number[] };
};
type Agreement = {
  synthetic: boolean;
  pairs: AgreementPair[];
  unpaired_source_indices: number[];
  rejected_pairs: unknown[];
  max_hours: number;
  min_cells: number;
  limitations: string[];
};
function scatterAgreement(
  band: AgreementBand,
  cells: { rows: number[]; columns: number[] },
  comparisonDay: string,
): SVGSVGElement {
  const ns = "http://www.w3.org/2000/svg",
    svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 620 500");
  svg.setAttribute("role", "img");
  svg.setAttribute(
    "aria-label",
    `${band.band} paired reflectance scatter; diagonal means agreement`,
  );
  const data = band.scatter;
  const numbers = [
    ...data.reference,
    ...data.current,
    ...(data.before_local_bandpass ?? []),
  ];
  const low = Math.min(0, ...numbers),
    high = Math.max(...numbers, low + 0.01),
    pad = (high - low) * 0.05;
  const minimum = low - pad,
    maximum = high + pad,
    x = (v: number) => 100 + ((v - minimum) / (maximum - minimum)) * 420,
    y = (v: number) => 450 - ((v - minimum) / (maximum - minimum)) * 420;
  function element(
    tag: string,
    attributes: Record<string, string | number>,
    text?: string,
  ) {
    const node = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attributes))
      node.setAttribute(key, String(value));
    if (text !== undefined) node.textContent = text;
    svg.append(node);
    return node;
  }
  element("rect", {
    x: 100,
    y: 30,
    width: 420,
    height: 420,
    fill: "#fff",
    stroke: "#bbcbd8",
  });
  for (let i = 0; i <= 4; i++) {
    const value = minimum + ((maximum - minimum) * i) / 4;
    element("line", {
      x1: x(value),
      x2: x(value),
      y1: 30,
      y2: 450,
      stroke: "#e4eaf0",
    });
    element("line", {
      x1: 100,
      x2: 520,
      y1: y(value),
      y2: y(value),
      stroke: "#e4eaf0",
    });
    element(
      "text",
      {
        x: x(value),
        y: 472,
        "text-anchor": "middle",
        fill: "#4d6376",
        "font-size": 12,
      },
      value.toFixed(2),
    );
    element(
      "text",
      {
        x: 90,
        y: y(value) + 4,
        "text-anchor": "end",
        fill: "#4d6376",
        "font-size": 12,
      },
      value.toFixed(2),
    );
  }
  element("line", {
    x1: x(minimum),
    y1: y(minimum),
    x2: x(maximum),
    y2: y(maximum),
    stroke: "#698092",
    "stroke-dasharray": "5 4",
  });
  const draw = (values: number[], color: string) =>
    values.forEach((v, i) => {
      const point = element("circle", {
        cx: x(data.reference[i]),
        cy: y(v),
        r: 2.2,
        fill: color,
        opacity: 0.45,
        style: "cursor:pointer",
      });
      const title = document.createElementNS(ns, "title");
      title.textContent = `Cell ${cells.rows[i]}, ${cells.columns[i]} · OLI ${data.reference[i].toFixed(5)} · MSI ${v.toFixed(5)}; click to inspect`;
      point.append(title);
      point.addEventListener("click", () => {
        const date =
          report?.timeline.findIndex((frame) => frame.day === comparisonDay) ??
          -1;
        if (date >= 0) selectDate(date);
        void inspect(cells.rows[i], cells.columns[i]);
      });
    });
  if (data.before_local_bandpass) draw(data.before_local_bandpass, "#b87621");
  draw(data.current, "#23668b");
  element(
    "text",
    {
      x: 310,
      y: 495,
      "text-anchor": "middle",
      fill: "#314f67",
      "font-size": 13,
    },
    "Landsat OLI surface reflectance / unit 1",
  );
  element(
    "text",
    {
      transform: "translate(18 240) rotate(-90)",
      "text-anchor": "middle",
      fill: "#314f67",
      "font-size": 13,
    },
    "Sentinel-2 MSI surface reflectance / unit 1",
  );
  element(
    "text",
    { x: 100, y: 15, fill: "#23668b", "font-size": 12 },
    "Current stack",
  );
  if (data.before_local_bandpass)
    element(
      "text",
      { x: 230, y: 15, fill: "#9c631a", "font-size": 12 },
      "Before local bandpass adjustment",
    );
  return svg;
}
function renderAgreement(result: Agreement) {
  const container = $("agreement-result");
  container.replaceChildren();
  const summary = document.createElement("p");
  summary.textContent = `${result.synthetic ? "Synthetic observations" : "Satellite observations"} · ${result.pairs.length} accepted pairs · ${result.unpaired_source_indices.length} unpaired scenes · ${result.rejected_pairs.length} candidate pairs rejected for insufficient common clear support.`;
  container.append(summary);
  if (!result.pairs.length) {
    const note = document.createElement("p");
    note.className = "note";
    note.textContent =
      "No pair meets the timestamp and clear-overlap requirements. Review the selected sensors, scene inventory and separation limit. A larger limit includes more potential surface change.";
    container.append(note);
    return;
  }
  const controls = document.createElement("div");
  controls.className = "agreement-controls";
  const pairLabel = document.createElement("label");
  pairLabel.textContent = "Acquisition pair";
  const select = document.createElement("select");
  select.id = "agreement-pair";
  result.pairs.forEach((pair, i) => {
    const option = document.createElement("option");
    option.value = String(i);
    option.textContent = `${pair.reference.datetime.slice(0, 10)} ${pair.reference.platform} / ${pair.comparison.datetime.slice(0, 10)} ${pair.comparison.platform}`;
    select.append(option);
  });
  pairLabel.append(select);
  const bandLabel = document.createElement("label");
  bandLabel.textContent = "Scatter band";
  const bandSelect = document.createElement("select");
  bandSelect.id = "agreement-band";
  for (const band of result.pairs[0].bands) {
    const option = document.createElement("option");
    option.value = band.band;
    option.textContent = band.band;
    bandSelect.append(option);
  }
  bandSelect.value = "nir";
  bandLabel.append(bandSelect);
  controls.append(pairLabel, bandLabel);
  const detail = document.createElement("p");
  detail.className = "agreement-source";
  const numbers = document.createElement("p");
  const grid = document.createElement("div");
  grid.className = "agreement-grid";
  const tableWrap = document.createElement("div");
  tableWrap.className = "table-scroll";
  const chart = document.createElement("div");
  chart.id = "agreement-scatter";
  grid.append(tableWrap, chart);
  const plotNote = document.createElement("p");
  plotNote.className = "note";
  const limits = document.createElement("p");
  limits.className = "note";
  limits.textContent =
    "Residuals include real temporal change, viewing geometry, atmospheric correction, bandpass, spatial response and registration differences. Shared grids do not establish image-based coregistration. Correlated pixels do not provide independent replicates; there is no automatic accuracy or significance claim.";
  const download = document.createElement("a");
  download.textContent =
    "Download pair metrics, sampled cells and input checksums";
  download.href = URL.createObjectURL(
    new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
  );
  download.download = `${report?.id}-sensor-agreement.json`;
  download.onclick = () =>
    setTimeout(() => URL.revokeObjectURL(download.href), 10000);
  container.append(controls, detail, numbers, grid, plotNote, limits, download);
  function update() {
    const pair = result.pairs[Number(select.value)],
      band =
        pair.bands.find((b) => b.band === bandSelect.value) ?? pair.bands[0];
    detail.textContent = `Reference: ${pair.reference.id} · ${pair.reference.datetime}. Comparison: ${pair.comparison.id} · ${pair.comparison.datetime}.`;
    numbers.textContent = `${pair.separation_hours.toFixed(2)} hours apart · ${pair.common_clear_cells.toLocaleString()} common clear cells (${fraction(pair.common_clear_fraction)} of AOI). NDVI bias ${pair.ndvi?.bias.toFixed(5) ?? "—"}; RMSE ${pair.ndvi?.rmse.toFixed(5) ?? "—"}. Median spectral angle ${pair.spectral_angle.median?.toFixed(3) ?? "—"}°.`;
    const table = document.createElement("table"),
      head = table.createTHead().insertRow();
    for (const text of [
      "Band / unit 1",
      "Bias",
      "RMSE · before local adjustment",
      "RMSE · current",
      "Correlation",
    ]) {
      const th = document.createElement("th");
      th.textContent = text;
      head.append(th);
    }
    const body = table.createTBody();
    for (const entry of pair.bands) {
      const row = body.insertRow();
      for (const text of [
        entry.band,
        entry.current.bias.toFixed(5),
        entry.before_local_bandpass?.rmse.toFixed(5) ?? "—",
        entry.current.rmse.toFixed(5),
        entry.current.correlation?.toFixed(4) ?? "—",
      ])
        row.insertCell().textContent = text;
    }
    tableWrap.replaceChildren(table);
    chart.replaceChildren(
      scatterAgreement(
        band,
        pair.scatter_cells,
        pair.comparison.datetime.slice(0, 10),
      ),
    );
    plotNote.textContent = `Scatter: ${band.scatter.reference.length} deterministic sampled common-clear cells (select a point to inspect its cell); table statistics use all ${pair.common_clear_cells.toLocaleString()} paired cells. ${pair.before_local_bandpass_available ? "Before values reverse the recorded local affine transform on these same QA-masked, resampled cells." : "No reversible local bandpass transform is recorded; before-adjustment scores are unavailable."}`;
  }
  select.onchange = update;
  bandSelect.onchange = update;
  update();
}
$("compare-sensors").onclick = async () => {
  if (!report) return;
  const id = report.id,
    button = $<HTMLButtonElement>("compare-sensors");
  button.disabled = true;
  $("agreement-result").textContent =
    "Matching timestamps and measuring common clear spectra…";
  try {
    const hours = Number(input("agreement-hours")),
      cells = Number(input("agreement-cells"));
    if (
      !Number.isFinite(hours) ||
      hours <= 0 ||
      hours > 168 ||
      !Number.isInteger(cells) ||
      cells < 1
    )
      throw new Error(
        "Choose a separation of 0–168 hours and a positive integer clear-cell count.",
      );
    const result = await api<Agreement>(
      `/api/runs/${id}/agreement?max_hours=${hours}&min_cells=${cells}`,
    );
    if (report?.id === id) renderAgreement(result);
  } catch (error) {
    if (report?.id === id)
      $("agreement-result").textContent =
        error instanceof Error ? error.message : String(error);
  } finally {
    button.disabled = false;
  }
};
type ErrorMetrics = {
  samples: number;
  mae: number | null;
  rmse: number | null;
  bias: number | null;
};
type Validation = {
  synthetic: boolean;
  index: string;
  max_gap_days: number;
  acquisition_days: number;
  summary: {
    held_out_clear_cells: number;
    scored_cells: number;
    scored_fraction: number | null;
    scored_dates: number;
    linear: ErrorMetrics;
    nearest: ErrorMetrics;
  };
  folds: {
    day: string;
    scored_fraction: number | null;
    scored_cells: number;
    median_bracket_days: number | null;
    linear: ErrorMetrics;
    nearest: ErrorMetrics;
  }[];
  limitations: string[];
};
$("validate-series").onclick = async () => {
  if (!report) return;
  const id = report.id,
    button = $<HTMLButtonElement>("validate-series");
  button.disabled = true;
  $("validation-result").textContent = "Evaluating whole-date holdouts…";
  try {
    const result = await api<Validation>(`/api/runs/${id}/validation`);
    if (report?.id !== id) return;
    const container = $("validation-result");
    container.replaceChildren();
    const summary = document.createElement("p");
    summary.textContent = `${result.synthetic ? "Synthetic observations" : "Satellite observations"} · ${result.index.toUpperCase()} (unit 1) · maximum bracket ${result.max_gap_days} days. ${result.summary.scored_cells.toLocaleString()} of ${result.summary.held_out_clear_cells.toLocaleString()} clear cell dates scored (${fraction(result.summary.scored_fraction ?? 0)}), across ${result.summary.scored_dates} of ${result.acquisition_days} held-out dates. Unscored dates remain in the coverage denominator.`;
    const metrics = document.createElement("table");
    const head = metrics.createTHead().insertRow();
    for (const text of ["Method · paired cells", "MAE", "RMSE", "Bias"]) {
      const th = document.createElement("th");
      th.textContent = text;
      head.append(th);
    }
    const body = metrics.createTBody();
    const number = (value: number | null) =>
      value === null ? "—" : value.toFixed(5);
    for (const [name, value] of [
      ["Linear", result.summary.linear],
      ["Nearest bracket", result.summary.nearest],
    ] as const) {
      const row = body.insertRow();
      for (const text of [
        name,
        number(value.mae),
        number(value.rmse),
        number(value.bias),
      ])
        row.insertCell().textContent = text;
    }
    const scroll = document.createElement("div");
    scroll.className = "table-scroll";
    const dates = document.createElement("table"),
      dateHead = dates.createTHead().insertRow();
    for (const text of [
      "Held-out UTC day",
      "Scored / clear",
      "Bracket median / d",
      "Linear RMSE",
      "Nearest RMSE",
    ]) {
      const th = document.createElement("th");
      th.textContent = text;
      dateHead.append(th);
    }
    const rows = dates.createTBody();
    for (const fold of result.folds) {
      const row = rows.insertRow();
      for (const text of [
        fold.day,
        fold.scored_fraction === null ? "—" : fraction(fold.scored_fraction),
        fold.median_bracket_days?.toFixed(1) ?? "—",
        number(fold.linear.rmse),
        number(fold.nearest.rmse),
      ])
        row.insertCell().textContent = text;
    }
    scroll.append(dates);
    const note = document.createElement("p");
    note.className = "note";
    note.textContent =
      "Clear satellite measurements are a reference, not independent ground truth. Neighboring cells are correlated. These scores do not establish reconstruction accuracy under real clouds or calibrated uncertainty. Retrospective evaluation uses future observations.";
    const download = document.createElement("a");
    download.textContent = "Download evaluation JSON and input checksums";
    download.href = URL.createObjectURL(
      new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
    );
    download.download = `${id}-temporal-validation.json`;
    download.onclick = () =>
      setTimeout(() => URL.revokeObjectURL(download.href), 10000);
    container.append(summary, metrics, scroll, note, download);
  } catch (error) {
    if (report?.id === id)
      $("validation-result").textContent =
        error instanceof Error ? error.message : String(error);
  } finally {
    button.disabled = false;
  }
};
$("recipe").onsubmit = (e) => {
  e.preventDefault();
  void run();
};
$("date-slider").oninput = () => selectDate(Number(input("date-slider")));
$("support-toggle").onclick = () => {
  support = !support;
  $("support-toggle").textContent = support ? "Show index" : "Show support";
  $("support-toggle").setAttribute("aria-pressed", String(support));
  showFrame();
};
for (const id of ["frame", "composite"])
  $(id).onclick = (e) => {
    if (!report) return;
    const rect = $(id).getBoundingClientRect();
    void inspect(
      Math.min(
        report.grid.height - 1,
        Math.floor(((e.clientY - rect.top) / rect.height) * report.grid.height),
      ),
      Math.min(
        report.grid.width - 1,
        Math.floor(((e.clientX - rect.left) / rect.width) * report.grid.width),
      ),
    );
  };
$("cell-form").onsubmit = (e) => {
  e.preventDefault();
  void inspect(Number(input("cell-row")), Number(input("cell-col")));
};
$("clear-pixel").onclick = () => {
  clearPixel();
  showFrame();
};
$("pixel-csv").onclick = () => {
  if (!pixel) return;
  const p = pixel;
  const columns = [
    "day",
    "value",
    "support",
    "bracket_days",
    "left_id",
    "left_datetime",
    "right_id",
    "right_datetime",
    "row",
    "col",
    "longitude",
    "latitude",
    "index",
    "units",
    "synthetic",
  ];
  const rows = p.series.map((s) => [
    s.day,
    s.value,
    kinds[s.support],
    s.bracket_days,
    s.left_source?.id,
    s.left_source?.datetime,
    s.right_source?.id,
    s.right_source?.datetime,
    p.row,
    p.col,
    p.longitude,
    p.latitude,
    p.index,
    p.units,
    p.synthetic,
  ]);
  download(
    `rslib-${p.run_id}-r${p.row}-c${p.col}.csv`,
    [columns, ...rows]
      .map((row) =>
        row.map((v) => `"${String(v ?? "").replaceAll('"', '""')}"`).join(","),
      )
      .join("\r\n") + "\r\n",
    "text/csv",
  );
};
$("save-recipe").onclick = () => {
  try {
    download(
      "rslib-optical-recipe.json",
      JSON.stringify(recipe(), null, 2) + "\n",
      "application/json",
    );
  } catch (error) {
    $("status").textContent = String(error);
  }
};
$("load-recipe").onclick = () => $<HTMLInputElement>("recipe-file").click();
$("recipe-file").onchange = async () => {
  try {
    const file = $<HTMLInputElement>("recipe-file").files?.[0];
    if (!file) return;
    setRecipe(JSON.parse(await file.text()) as Recipe);
    $("status").textContent = "Recipe loaded. Run preparation to apply it.";
  } catch (error) {
    $("status").textContent = String(error);
  }
};

async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : JSON.stringify(result.detail),
    );
  return result as T;
}
function defaultRecipe(demo = false): Recipe {
  return {
    demo,
    bbox: { west: -44.66, south: -22.41, east: -44.64, north: -22.39 },
    datetime: "2026-06-01/2026-07-16",
    sensors: ["sentinel-2", "landsat"],
    resolution: 30,
    step_days: 5,
    max_gap_days: 20,
    cloud_buffer_m: 60,
    min_clear_fraction: 0.9,
    max_scenes_per_sensor: demo ? 4 : 12,
    max_cloud: 40,
    index: "ndvi",
    refresh: false,
    fields: demo ? exampleAreas() : [],
    coverage_target: demo ? null : 0.8,
  };
}
function exampleAreas(): Boundary[] {
  return [
    {
      id: "west",
      name: "Western area",
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [-44.659, -22.409],
            [-44.651, -22.409],
            [-44.651, -22.391],
            [-44.659, -22.391],
            [-44.659, -22.409],
          ],
        ],
      },
    },
    {
      id: "east",
      name: "Eastern area",
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [-44.65, -22.409],
            [-44.641, -22.409],
            [-44.641, -22.391],
            [-44.646, -22.393],
            [-44.65, -22.391],
            [-44.65, -22.409],
          ],
        ],
      },
    },
  ];
}
function currentBounds(): Bounds {
  const b = recipe().bbox;
  return [b.west, b.south, b.east, b.north];
}
function renderMap() {
  if (!map) return;
  const layer = input("map-layer");
  $("support-legend").hidden = layer !== "support" && !support;
  const frame = report?.timeline[position];
  $("map-date").textContent = frame ? `${frame.day} UTC` : "No run";
  const image =
    layer === "composite"
      ? report?.display?.composite_url
      : layer === "support"
        ? frame?.map_support_url
        : layer === "index"
          ? frame?.map_image_url
          : undefined;
  const selected = selectedArea()?.id;
  try {
    map.update({
      bounds: currentBounds(),
      fields: boundaries,
      selected,
      image,
      imageBounds: report?.display?.bounds,
      opacity: Number(input("map-opacity")) / 100,
      base: checked("map-base"),
      inspectCells: input("map-interaction") === "cell",
      point: pixel ? [pixel.longitude, pixel.latitude] : undefined,
    });
  } catch {
    /* Keep the last valid extent while coordinates are being edited. */
  }
}
function invalidateRun() {
  report = undefined;
  pixel = undefined;
  inspection++;
  $("results").hidden = true;
  $("empty").hidden = false;
  $("run-info").textContent =
    "Area boundaries changed. Run preparation to compute their time series.";
  renderMap();
}
function renderBoundaries() {
  $("boundary-count").textContent = String(boundaries.length);
  $("boundary-list").replaceChildren(
    ...boundaries.map((f) => {
      const row = document.createElement("div");
      const name = document.createElement("span");
      name.textContent = f.name;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `Remove ${f.name}`);
      remove.onclick = () => {
        boundaries = boundaries.filter((b) => b.id !== f.id);
        invalidateRun();
        renderBoundaries();
      };
      row.append(name, remove);
      return row;
    }),
  );
  renderMap();
}
function renderScopes() {
  const select = $<HTMLSelectElement>("series-scope");
  select.replaceChildren(
    new Option("Acquisition AOI", "aoi"),
    new Option("Selected cell", "pixel"),
    ...(report?.fields ?? []).map((f) => new Option(f.name, "field:" + f.id)),
  );
  select.options[1].disabled = !pixel;
}
function selectArea(id: string) {
  clearPixel();
  $<HTMLSelectElement>("series-scope").value = "field:" + id;
  showFrame();
}
function renderAreaStatistics() {
  if (!report) return;
  const fields = report.fields ?? [];
  $("field-statistics").hidden = !fields.length;
  if (report.fields_csv_url)
    $<HTMLAnchorElement>("fields-csv").href = report.fields_csv_url;
  $("field-rows").replaceChildren(
    ...fields.map((f) => {
      const frame = f.timeline[position],
        row = document.createElement("tr");
      row.className = selectedArea()?.id === f.id ? "selected" : "";
      for (const text of [
        f.name,
        (f.area_m2 / 10000).toFixed(2),
        fraction(frame.observed_fraction),
        fraction(frame.estimated_fraction),
        fraction(frame.missing_fraction),
        frame.observed_mean?.toFixed(4) ?? "—",
      ]) {
        const cell = document.createElement("td");
        cell.textContent = text;
        row.append(cell);
      }
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      row.onclick = () => selectArea(f.id);
      row.onkeydown = (e) => {
        if (e.key === "Enter") selectArea(f.id);
      };
      return row;
    }),
  );
  const field = selectedArea();
  $("area-date-table").hidden = !field;
  $("area-detail").textContent = field
    ? `Fractional polygon/cell intersections in ${field.area_crs}. Field area: ${(field.area_m2 / 10000).toFixed(2)} ha. Observed on every requested date: ${(field.fixed_observed_area_m2 / 10000).toFixed(2)} ha. Means assume each analysis cell is spatially constant.`
    : "Select an area to review coverage by date. Areas are measured in the projected analysis CRS; boundary cells contribute their intersected area.";
  $("field-dates").replaceChildren(
    ...(field?.timeline ?? []).map((frame, i) => {
      const row = document.createElement("tr");
      row.className = i === position ? "selected" : "";
      for (const text of [
        frame.day,
        `${fraction(frame.observed_fraction)} · ${(frame.observed_area_m2 / 10000).toFixed(2)} ha`,
        `${fraction(frame.estimated_fraction)} · ${(frame.estimated_area_m2 / 10000).toFixed(2)} ha`,
        `${fraction(frame.missing_fraction)} · ${(frame.missing_area_m2 / 10000).toFixed(2)} ha`,
        frame.observed_mean?.toFixed(4) ?? "—",
        frame.supported_mean?.toFixed(4) ?? "—",
      ]) {
        const cell = document.createElement("td");
        cell.textContent = text;
        row.append(cell);
      }
      row.tabIndex = 0;
      row.onclick = () => selectDate(i);
      row.onkeydown = (e) => {
        if (e.key === "Enter") selectDate(i);
      };
      return row;
    }),
  );
}
async function projectList() {
  const result = await api<{
    projects: { id: string; name: string; field_count: number }[];
  }>("/api/projects");
  $<HTMLSelectElement>("project-select").replaceChildren(
    new Option("Unsaved workspace", ""),
    ...result.projects.map(
      (p) => new Option(`${p.name} · ${p.field_count} areas`, p.id),
    ),
  );
  $<HTMLSelectElement>("project-select").value = project?.id ?? "";
}
function renderHistory() {
  $("project-history").hidden = !project;
  $("workspace-title").textContent = project?.name ?? "Optical monitoring";
  $("project-state").textContent = project
    ? `Revision ${project.revision} · ${project.runs.length} saved runs`
    : "Unsaved workspace";
  $("run-history").replaceChildren(
    ...(project?.runs ?? []).map((run) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `${run.created.slice(0, 19).replace("T", " ")} UTC · revision ${run.recipe_revision} · ${run.summary.observations} scenes · ${fraction(run.summary.unsupported_fraction)} missing${run.synthetic ? " · synthetic" : ""}`;
      button.onclick = () => void openRun(run.id);
      return button;
    }),
  );
}
async function saveProject() {
  const spec = { name: input("project-name").trim(), recipe: recipe() };
  if (!spec.name) throw new Error("Enter a project name.");
  project = await api<Project>(
    project ? `/api/projects/${project.id}` : "/api/projects",
    project ? { ...spec, revision: project.revision } : spec,
  );
  renderHistory();
  await projectList();
  const url = new URL(location.href);
  url.searchParams.set("project", project.id);
  history.replaceState(null, "", url);
  return project;
}
function leaveJob() {
  watchVersion++;
  activeJob = undefined;
  setBusy(false);
  $("job-panel").hidden = true;
  const url = new URL(location.href);
  url.searchParams.delete("job");
  history.replaceState(null, "", url);
}
async function openRun(id: string) {
  leaveJob();
  try {
    const r = await api<Report>(`/api/runs/${id}/manifest.json`);
    if (!r.timeline || !r.request)
      throw new Error("This is not an optical run.");
    report = r;
    setRecipe(r.request);
    render();
    map?.fit(currentBounds());
    $("status").textContent =
      `Saved run loaded. ${fraction(r.summary.unsupported_fraction)} of pixel dates have no value.`;
    $("status").dataset.state = "complete";
  } catch (error) {
    $("status").textContent = String(error);
  }
}
async function openProject(id: string, run?: string) {
  leaveJob();
  project = await api<Project>(`/api/projects/${id}`);
  setRecipe(project.recipe);
  $<HTMLInputElement>("project-name").value = project.name;
  invalidateRun();
  renderHistory();
  await projectList();
  const url = new URL(location.href);
  url.searchParams.set("project", id);
  url.searchParams.delete("run");
  history.replaceState(null, "", url);
  const latest = project.runs[0];
  if (run) await openRun(run);
  else if (latest?.recipe_revision === project.revision)
    await openRun(latest.id);
  map?.fit(currentBounds());
}
function acceptBoundaries(fields: Boundary[]) {
  if (!fields.length || fields.length > 32)
    throw new Error("Import between 1 and 32 polygon areas.");
  if (new Set(fields.map((f) => f.id)).size !== fields.length)
    throw new Error("Area IDs must be unique.");
  for (const f of fields)
    if (!["Polygon", "MultiPolygon"].includes(f.geometry.type))
      throw new Error("Only Polygon and MultiPolygon features are supported.");
  boundaries = fields;
  if (input("source") !== "demo") {
    const points = fields.flatMap((f) =>
      f.geometry.type === "Polygon"
        ? f.geometry.coordinates.flat()
        : f.geometry.coordinates.flat(2),
    );
    const xs = points.map((p) => p[0]),
      ys = points.map((p) => p[1]);
    $<HTMLInputElement>("bbox").value = [
      Math.min(...xs),
      Math.min(...ys),
      Math.max(...xs),
      Math.max(...ys),
    ].join(",");
  }
  invalidateRun();
  renderBoundaries();
  map?.fit(currentBounds());
}
$("save-project").onclick = () =>
  void saveProject()
    .then(() => {
      $("status").textContent = "Project saved on this server.";
    })
    .catch((error) => {
      $("status").textContent = String(error);
    });
$("project-select").onchange = () => {
  const id = input("project-select");
  if (id)
    void openProject(id).catch((error) => {
      $("status").textContent = String(error);
    });
  else $("new-project").click();
};
$("new-project").onclick = () => {
  leaveJob();
  project = undefined;
  setRecipe(defaultRecipe());
  $<HTMLSelectElement>("project-select").value = "";
  $<HTMLInputElement>("project-name").value = "Untitled optical project";
  invalidateRun();
  renderHistory();
  history.replaceState(null, "", location.pathname);
  map?.fit(currentBounds());
};
$("example").onclick = () => {
  project = undefined;
  setRecipe(defaultRecipe(true));
  $<HTMLInputElement>("project-name").value = "Synthetic optical example";
  $<HTMLSelectElement>("project-select").value = "";
  renderHistory();
  void run();
};
$("series-scope").onchange = () => {
  if (input("series-scope") !== "pixel") clearPixel();
  showFrame();
};
$("area-metric").onchange = chart;
for (const id of ["map-layer", "map-base", "map-opacity", "map-interaction"])
  $(id).oninput = renderMap;
$("fit-area").onclick = () => {
  try {
    map?.fit(currentBounds());
  } catch (error) {
    $("map-message").textContent = String(error);
  }
};
$("draw-area").onclick = () => {
  map?.startDrawing();
  $("finish-area").hidden = false;
  $("cancel-area").hidden = false;
};
function stopDrawing() {
  map?.cancelDrawing();
  $("finish-area").hidden = true;
  $("cancel-area").hidden = true;
}
$("cancel-area").onclick = stopDrawing;
$("finish-area").onclick = () => {
  const geometry = map?.finishDrawing();
  if (!geometry) return;
  try {
    const f: Boundary = {
      id: crypto.randomUUID(),
      name: input("boundary-name").trim() || `Area ${boundaries.length + 1}`,
      geometry,
    };
    acceptBoundaries([...boundaries, f]);
    $("finish-area").hidden = true;
    $("cancel-area").hidden = true;
    $<HTMLInputElement>("boundary-name").value =
      `Area ${boundaries.length + 1}`;
    $("map-message").textContent =
      "Area added. Run preparation to calculate its statistics.";
  } catch (error) {
    $("map-message").textContent = String(error);
  }
};
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") stopDrawing();
});
$("import-areas").onclick = () => $<HTMLInputElement>("areas-file").click();
$("areas-file").onchange = async () => {
  try {
    const file = $<HTMLInputElement>("areas-file").files?.[0];
    if (!file) return;
    if (file.size > 2_000_000)
      throw new Error("GeoJSON exceeds 2 MB; simplify or split the areas.");
    const json = JSON.parse(await file.text());
    const fc: FeatureCollection =
      json.type === "FeatureCollection"
        ? json
        : {
            type: "FeatureCollection",
            features: [
              json.type === "Feature"
                ? json
                : { type: "Feature", properties: {}, geometry: json },
            ],
          };
    acceptBoundaries(
      fc.features.map((f, i) => ({
        id: String(f.id ?? f.properties?.id ?? `area-${i + 1}`),
        name: String(f.properties?.name ?? `Area ${i + 1}`),
        geometry: f.geometry as Boundary["geometry"],
      })),
    );
    $("status").textContent =
      "Areas imported. Save the project or run preparation.";
  } catch (error) {
    $("status").textContent = String(error);
  }
};
for (const id of ["start", "end"])
  $(id).oninput = () => {
    importedInterval = undefined;
  };
$("bbox").onchange = () => {
  renderMap();
};
try {
  map = new OpticalMap(
    $<HTMLDivElement>("optical-map"),
    (lon, lat) => {
      if (report) void inspectQuery(`longitude=${lon}&latitude=${lat}`);
      else
        $("map-message").textContent =
          "Run preparation before inspecting cell values.";
    },
    (id) => {
      if (report?.fields?.some((f) => f.id === id)) selectArea(id);
      else
        $("map-message").textContent =
          "Run preparation to calculate this area’s statistics.";
    },
    (text) => {
      $("map-message").textContent = text;
    },
  );
  renderMap();
} catch {
  $("map-message").textContent =
    "Map rendering is unavailable. GeoJSON import, analysis and raster inspection remain available.";
}
void (async () => {
  try {
    await projectList();
    await listJobs();
    const params = new URLSearchParams(location.search),
      id = params.get("project"),
      run = params.get("run"),
      job = params.get("job");
    if (job && /^[a-f0-9]{32}$/.test(job)) await followJob(job, true);
    else if (id) await openProject(id, run ?? undefined);
    else if (run && /^[a-f0-9]{32}$/.test(run)) await openRun(run);
  } catch (error) {
    $("status").textContent = String(error);
  }
})();

$("workspace-run").onclick = () => $<HTMLFormElement>("recipe").requestSubmit();
new MutationObserver(() => {
  const target = $("workspace-status");
  target.textContent = $("status").textContent;
  target.dataset.state = $("status").dataset.state;
  target.hidden = !target.textContent;
}).observe($("status"), {
  childList: true,
  attributes: true,
  subtree: true,
  characterData: true,
});
