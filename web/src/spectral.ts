import "./spectral.css";

type Recipe = {
  run_id: string;
  source_index: number;
  components: number;
  endmembers: number;
  projection: "affine" | "projective";
  seed: number;
  input_checksums?: Record<string, string>;
};
type Job = {
  id: string;
  kind: "spectral" | "optical";
  run_id: string;
  status: string;
  attempt: number;
  recipe: Recipe;
  manifest_url: string | null;
  progress: { message: string };
  error: { message: string; code: string } | null;
};
type Parent = {
  id: string;
  synthetic: boolean;
  observations: { id: string; datetime: string; platform: string }[];
  bands: string[];
  summary: {
    observed_fraction: number;
    filled_fraction: number;
    unsupported_fraction: number;
  };
};
type Display = {
  filename: string;
  title: string;
  description: string;
  minimum: number[];
  maximum: number[];
};
type Analysis = {
  id: string;
  run_id: string;
  synthetic: boolean;
  recipe: Recipe;
  source: { id: string; datetime: string };
  input_checksums: Record<string, string>;
  grid: { crs: string; transform: number[]; height: number; width: number };
  pca: { loadings: number[][]; variance_fraction: number[] };
  vca: {
    bands: string[];
    projection: string;
    seed: number;
    cells: { row: number; column: number }[];
    observed_spectra: number[][];
    projected_endmembers: number[][];
  };
  fcls: {
    valid_cells: number;
    rmse_median: number;
    rmse_p95: number;
    maximum_optimality_gap: number;
  };
  displays: Display[];
  limitations: string[];
  parent: { summary: Parent["summary"]; coverage_notes: string[] };
};
type Pixel = {
  analysis_id: string;
  row: number;
  col: number;
  easting_m: number;
  northing_m: number;
  valid: boolean;
  bands: string[];
  observed: (number | null)[];
  reconstructed: (number | null)[];
  abundance: (number | null)[];
  scores: (number | null)[];
  rmse: number | null;
};
const $ = <T extends HTMLElement = HTMLElement>(id: string) =>
  document.getElementById(id) as T;
$("spectral-app").innerHTML =
  `<header><a href="/workflows.html">RSLIB / Spectral analysis</a><nav><a id="parent-link" href="/workflows.html">Optical project</a><a href="/showcase/">Development captures</a><a href="/showcase/research.html">Research methods</a></nav></header>
<div class="layout"><aside><h2>Observed-scene analysis</h2><p class="muted">PCA outputs and VCA/FCLS use the selected source. Each job saves its parameters and pins the input stack.</p>
<form id="form"><fieldset id="spectral-controls"><label>Completed optical run ID<input id="run-id" pattern="[a-f0-9]{32}" required></label><button id="load" type="button">Load source inventory</button><p id="parent-state" class="muted">Open a completed optical run.</p><label>Fit source acquisition<select id="source-index" required></select></label>
<div class="pair"><label>PCA components<input id="components" type="number" min="1" max="6" step="1" value="3" required></label><label>Endmembers<input id="endmembers" type="number" min="2" max="6" step="1" value="3" required></label></div>
<label>VCA projection<select id="projection"><option value="affine">Affine · p−1 centered dimensions</option><option value="projective">Projective · p uncentered dimensions</option></select></label><label>Random seed<input id="seed" type="number" min="0" max="4294967295" value="0" step="1" required></label><p class="muted">Fit uses complete QA-valid observed spectra. PCA components control the exported scores; VCA uses p−1 or p dimensions from its endmember count. Source exclusions remain missing.</p><button id="submit" class="primary" disabled>Run spectral analysis</button></fieldset></form>
<details class="downloads"><summary>Reopen saved spectral jobs</summary><p class="muted">Most recent spectral jobs for the loaded run; direct job links remain available.</p><button id="refresh-history">Refresh</button><div id="history"></div></details></aside>
<main><h1>Spectral analysis</h1><div id="status" role="status">Load a source run to start, or reopen a saved job.</div><section id="job-panel" class="panel" hidden><h2 id="job-title"></h2><p id="job-id" class="mono"></p><div class="actions"><button id="cancel">Cancel job</button><button id="retry">Retry saved job</button><button id="reconnect">Reconnect</button></div><ol id="journal"></ol></section>
<div id="result" hidden><section class="panel"><h2 id="source-title"></h2><p id="summary"></p><p id="fit-parameters" class="muted"></p><p class="warning">Fractions describe the selected geometric endmembers. Material identity and fraction accuracy have no independent validation.</p><div id="exports" class="actions"></div></section>
<section class="panel"><div id="maps" class="maps"></div><p class="muted">Click any raster to inspect that exact grid cell. All views share the same grid. Checkerboard: missing or excluded. Raster colors use the recorded display stretches.</p><label>Additional component map<select id="extra-display"></select></label><div id="extra-map" class="map-card" style="max-width:380px"></div></section>
<div class="details"><section class="panel"><h2 id="cell-title">Select a cell</h2><p id="cell-detail"></p><div id="spectrum"></div><table><thead><tr><th>Band</th><th>Observed</th><th>Reconstructed</th><th>Residual</th></tr></thead><tbody id="values"></tbody></table></section>
<section class="panel"><h2>Endmembers and cell fractions</h2><p class="muted">Select a source cell to inspect the observed spectrum that VCA selected.</p><table><thead><tr><th>Component</th><th>Source cell</th><th>Fraction</th></tr></thead><tbody id="members"></tbody></table><h3 style="margin-top:20px">PCA loadings</h3><label>Component<select id="loading-component"></select></label><p id="variance" class="muted"></p><table><thead><tr><th>Band</th><th>Loading</th></tr></thead><tbody id="loadings"></tbody></table></section></div>
<section class="panel"><h2>Parent temporal support</h2><p id="coverage"></p><ul id="coverage-notes"></ul><p class="muted">These support fractions describe the parent optical series; this analysis fits a single acquired scene.</p><details><summary>Assumptions and input identity</summary><ul id="limitations"></ul><pre id="checksums" class="mono"></pre></details></section></div></main></div>`;
let parent: Parent | undefined,
  analysis: Analysis | undefined,
  selected: Pixel | undefined,
  active: Job | undefined;
let activeId: string | undefined;
let watch = 0,
  picking = 0;
const fmt = (v: number | null | undefined, digits = 5) =>
  v == null ? "missing" : v.toFixed(digits);
const input = (id: string) => $(id) as HTMLInputElement;
function status(message: string, state = "ready") {
  $("status").textContent = message;
  $("status").dataset.state = state;
}
async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(
    path,
    body === undefined
      ? undefined
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      message =
        typeof payload.detail === "string"
          ? payload.detail
          : JSON.stringify(payload.detail);
    } catch {}
    throw new Error(message);
  }
  return response.json();
}
function fail(error: unknown) {
  status(error instanceof Error ? error.message : String(error), "error");
}
function busy(value: boolean) {
  $<HTMLFieldSetElement>("spectral-controls").disabled = value;
}
function restoreRecipe(r: Recipe) {
  input("run-id").value = r.run_id;
  for (const key of [
    "source_index",
    "components",
    "endmembers",
    "projection",
    "seed",
  ] as const) {
    input(key.replace("_", "-")).value = String(r[key]);
  }
}
async function loadParent(id = input("run-id").value) {
  parent = undefined;
  $<HTMLButtonElement>("submit").disabled = true;
  $<HTMLSelectElement>("source-index").replaceChildren();
  if (!/^[a-f0-9]{32}$/.test(id))
    throw new Error("Enter a completed optical run ID.");
  const result = await api<Parent>(`/api/runs/${id}/manifest.json`);
  if (!result.observations || !result.bands)
    throw new Error("This run is not an optical stack.");
  parent = result;
  input("run-id").value = id;
  $<HTMLSelectElement>("source-index").replaceChildren(
    ...result.observations.map(
      (s, i) =>
        new Option(
          `${s.datetime.slice(0, 10)} · ${s.platform} · ${s.id}`,
          String(i),
        ),
    ),
  );
  $("parent-state").textContent =
    `${result.synthetic ? "Synthetic fixture" : "Satellite observations"} · ${result.observations.length} acquisitions`;
  $<HTMLAnchorElement>("parent-link").href = `/workflows.html?run=${id}`;
  $<HTMLButtonElement>("submit").disabled = false;
  void historyList().catch(fail);
}
function recipe(): Recipe {
  if (!parent || input("run-id").value !== parent.id)
    throw new Error("Load the requested source inventory before submitting.");
  return {
    run_id: parent.id,
    source_index: Number(input("source-index").value),
    components: Number(input("components").value),
    endmembers: Number(input("endmembers").value),
    projection: input("projection").value as Recipe["projection"],
    seed: Number(input("seed").value),
  };
}
async function historyList() {
  const { jobs } = await api<{ jobs: Job[] }>(
    `/api/jobs${parent ? `?source_run_id=${parent.id}` : ""}`,
  );
  $("history").replaceChildren(
    ...jobs
      .filter((j) => j.kind === "spectral")
      .map((j) => {
        const button = document.createElement("button");
        button.textContent = `${j.status} · ${j.id.slice(0, 8)} · source ${j.recipe.source_index} · attempt ${j.attempt}`;
        button.onclick = () => void follow(j.id, true);
        return button;
      }),
  );
}
function paintJob(
  job: Job,
  events: {
    sequence: number;
    attempt: number;
    created: string;
    message: string;
    completed_cells?: number;
    total_cells?: number;
  }[],
) {
  active = job;
  $("job-panel").hidden = false;
  $("job-title").textContent = `${job.status} · attempt ${job.attempt}`;
  $("job-id").textContent = job.id;
  status(
    job.error
      ? `${job.error.code}: ${job.error.message}`
      : job.progress.message,
    job.status === "failed"
      ? "error"
      : job.status === "succeeded"
        ? "complete"
        : job.status,
  );
  $("cancel").hidden = !["queued", "running", "cancelling"].includes(
    job.status,
  );
  $<HTMLButtonElement>("cancel").disabled = job.status === "cancelling";
  $("retry").hidden = !["failed", "cancelled"].includes(job.status);
  $("reconnect").hidden = true;
  $("journal").replaceChildren(
    ...events.slice(-35).map((e) => {
      const li = document.createElement("li");
      li.textContent = `${e.created.slice(11, 19)} UTC · ${e.attempt} · ${e.message}${e.total_cells !== undefined ? ` (${e.completed_cells}/${e.total_cells} cells)` : ""}`;
      return li;
    }),
  );
}
async function follow(id: string, restore = false) {
  activeId = id;
  const version = ++watch;
  busy(true);
  picking++;
  analysis = undefined;
  selected = undefined;
  $("result").hidden = true;
  const url = new URL(location.href);
  url.searchParams.set("job", id);
  history.replaceState(null, "", url);
  let after = 0;
  const events: Parameters<typeof paintJob>[1] = [];
  try {
    while (version === watch) {
      const [job, journal] = await Promise.all([
        api<Job>(`/api/jobs/${id}`),
        api<{ events: Parameters<typeof paintJob>[1] }>(
          `/api/jobs/${id}/events?after=${after}`,
        ),
      ]);
      if (version !== watch) return;
      if (job.kind !== "spectral") throw new Error("Choose a spectral job.");
      if (restore) {
        try {
          await loadParent(job.recipe.run_id);
        } catch {
          $("parent-state").textContent =
            "Source inventory unavailable. Saved outputs remain available; a new job requires the pinned input.";
        }
        restoreRecipe(job.recipe);
        restore = false;
      }
      events.push(...journal.events);
      after = events.at(-1)?.sequence ?? after;
      paintJob(job, events);
      if (journal.events.length === 200) continue;
      if (["succeeded", "failed", "cancelled"].includes(job.status)) {
        // The parallel journal request can precede the final state commit.
        // Read again after observing a terminal state, then drain pagination.
        while (true) {
          const tail = await api<{ events: Parameters<typeof paintJob>[1] }>(
            `/api/jobs/${id}/events?after=${after}`,
          );
          if (version !== watch) return;
          events.push(...tail.events);
          after = events.at(-1)?.sequence ?? after;
          if (tail.events.length < 200) break;
        }
        paintJob(job, events);
        if (job.manifest_url) {
          const loaded = await api<Analysis>(job.manifest_url);
          if (version !== watch) return;
          analysis = loaded;
          render();
          status(
            "Spectral outputs and report available. Material-fraction accuracy is unvalidated.",
            "complete",
          );
        }
        await historyList();
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 450));
    }
  } catch (error) {
    if (version === watch) {
      fail(error);
      $("reconnect").hidden = false;
    }
  } finally {
    if (version === watch) busy(false);
  }
}
function rows(id: string, data: (string | HTMLElement)[][]) {
  $(id).replaceChildren(
    ...data.map((values) => {
      const row = document.createElement("tr");
      for (const value of values) {
        const cell = document.createElement("td");
        if (typeof value === "string") cell.textContent = value;
        else cell.append(value);
        row.append(cell);
      }
      return row;
    }),
  );
}
function mapCard(d: Display) {
  const r = analysis!,
    card = document.createElement("article");
  card.className = "map-card";
  const title = document.createElement("h3");
  title.textContent = d.title;
  const map = document.createElement("div");
  map.className = "map";
  const image = document.createElement("img");
  image.src = `/api/analyses/${r.id}/${d.filename}`;
  image.alt = d.title;
  image.dataset.layer = d.filename;
  const cross = document.createElement("span");
  cross.className = "cross";
  map.append(image, cross);
  image.onclick = (event) => {
    const box = image.getBoundingClientRect();
    const row = Math.max(
      0,
      Math.min(
        r.grid.height - 1,
        Math.floor(((event.clientY - box.top) / box.height) * r.grid.height),
      ),
    );
    const col = Math.max(
      0,
      Math.min(
        r.grid.width - 1,
        Math.floor(((event.clientX - box.left) / box.width) * r.grid.width),
      ),
    );
    void inspect(row, col);
  };
  const scale = document.createElement("div");
  scale.className = "scale";
  const distance = Math.max(
    1,
    Math.round((r.grid.width * r.grid.transform[0]) / 5),
  );
  scale.style.width = `${(distance / (r.grid.width * r.grid.transform[0])) * 100}%`;
  scale.textContent = `${distance} m`;
  const legend = document.createElement("p");
  legend.textContent =
    d.description +
    ` Display bounds: ${d.minimum.map((v) => fmt(v, 4)).join(", ")} → ${d.maximum.map((v) => fmt(v, 4)).join(", ")}.`;
  card.append(title, map, scale, legend);
  return card;
}
function extra() {
  const d = analysis?.displays.find(
    (d) => d.filename === input("extra-display").value,
  );
  $("extra-map").replaceChildren(...(d ? [mapCard(d)] : []));
  crosshairs();
}
function render() {
  const r = analysis!;
  $("result").hidden = false;
  $("source-title").textContent =
    `${r.synthetic ? "Synthetic" : "Satellite"} · ${r.source.id}`;
  $("summary").textContent =
    `${r.source.datetime} · ${r.grid.crs} · ${r.grid.width} × ${r.grid.height} cells · ${r.fcls.valid_cells.toLocaleString()} complete spectra. Median reflectance RMSE ${fmt(r.fcls.rmse_median)}; P95 ${fmt(r.fcls.rmse_p95)}.`;
  $("fit-parameters").textContent =
    `Saved fit: source ${r.recipe.source_index}; PCA ${r.recipe.components} components; ${r.recipe.endmembers} endmembers; ${r.recipe.projection} projection; seed ${r.recipe.seed}.`;
  $("exports").replaceChildren(
    ...[
      ["Printable project report", "report.html"],
      ["Complete artifact bundle", "bundle.zip"],
      ["Saved job request", "request.json"],
      ["Analysis JSON", "report.json"],
      ["PCA COG", "pca.tif"],
      ["Fractions COG", "abundance.tif"],
      ["Residual COG", "reconstruction-rmse.tif"],
    ].map(([label, file]) => {
      const a = document.createElement("a");
      a.textContent = label;
      a.href = `/api/analyses/${r.id}/${file}`;
      if (file === "report.html") {
        a.target = "_blank";
        a.rel = "noopener";
      } else a.download = file;
      return a;
    }),
  );
  $("maps").replaceChildren(...r.displays.slice(0, 4).map(mapCard));
  $<HTMLSelectElement>("extra-display").replaceChildren(
    new Option("No additional map", ""),
    ...r.displays.slice(4).map((d) => new Option(d.title, d.filename)),
  );
  extra();
  $<HTMLSelectElement>("loading-component").replaceChildren(
    ...r.pca.loadings.map((_, i) => new Option(`PC${i + 1}`, String(i))),
  );
  const c = r.parent.summary;
  $("coverage").textContent =
    `${(c.observed_fraction * 100).toFixed(1)}% observed · ${(c.filled_fraction * 100).toFixed(1)}% estimated · ${(c.unsupported_fraction * 100).toFixed(1)}% missing`;
  for (const [id, items] of [
    ["limitations", r.limitations],
    ["coverage-notes", r.parent.coverage_notes],
  ] as const) {
    $(id).replaceChildren(
      ...items.map((text) => {
        const li = document.createElement("li");
        li.textContent = text;
        return li;
      }),
    );
  }
  $("checksums").textContent = JSON.stringify(r.input_checksums, null, 2);
  loadings();
  const first = r.vca.cells[0];
  void inspect(first.row, first.column);
}
function crosshairs() {
  if (!analysis || !selected) return;
  for (const cross of Array.from(
    document.querySelectorAll<HTMLElement>(".cross"),
  )) {
    cross.hidden = false;
    cross.style.left = `${(selected.col / analysis.grid.width) * 100}%`;
    cross.style.top = `${(selected.row / analysis.grid.height) * 100}%`;
    cross.style.width = `${100 / analysis.grid.width}%`;
    cross.style.height = `${100 / analysis.grid.height}%`;
  }
}
function loadings() {
  if (!analysis) return;
  const i = Number(input("loading-component").value || 0);
  $("variance").textContent =
    `PC${i + 1} explains ${(100 * analysis.pca.variance_fraction[i]).toFixed(3)}% of training covariance variance. Cell score ${fmt(selected?.scores[i])}. Covariance PCA; no whitening or per-band standardization.`;
  rows(
    "loadings",
    analysis.vca.bands.map((b, k) => [b, fmt(analysis!.pca.loadings[i][k])]),
  );
}
async function inspect(row: number, col: number) {
  const r = analysis;
  if (!r) return;
  const ticket = ++picking;
  selected = undefined;
  $("members").replaceChildren();
  loadings();
  document
    .querySelectorAll<HTMLElement>(".cross")
    .forEach((e) => (e.hidden = true));
  $("cell-title").textContent = `Cell row ${row}, column ${col}`;
  $("cell-detail").textContent = "Reading source spectrum and fitted values…";
  $("values").replaceChildren();
  $("spectrum").replaceChildren();
  try {
    const p = await api<Pixel>(
      `/api/analyses/${r.id}/pixel?row=${row}&col=${col}`,
    );
    if (ticket !== picking || analysis?.id !== r.id) return;
    selected = p;
    document.body.dataset.row = String(row);
    document.body.dataset.col = String(col);
    crosshairs();
    rows(
      "members",
      r.vca.cells.map((cell, k) => {
        const button = document.createElement("button");
        button.textContent = `${cell.row}, ${cell.column}`;
        button.onclick = () => void inspect(cell.row, cell.column);
        return [`E${k + 1}`, button, fmt(p.abundance[k])];
      }),
    );
    loadings();
    if (!p.valid) {
      $("cell-detail").textContent =
        "Excluded or missing. No fitted fractions or spectrum at this cell.";
      return;
    }
    $("cell-detail").textContent =
      `Easting ${fmt(p.easting_m, 1)} m · northing ${fmt(p.northing_m, 1)} m · RMSE ${fmt(p.rmse)}`;
    rows(
      "values",
      p.bands.map((b, k) => [
        b,
        fmt(p.observed[k]),
        fmt(p.reconstructed[k]),
        fmt(p.reconstructed[k]! - p.observed[k]!),
      ]),
    );
    plot(p);
  } catch (error) {
    if (ticket === picking) {
      $("cell-detail").textContent = String(error);
      fail(error);
    }
  }
}
function plot(p: Pixel) {
  const values = [...p.observed, ...p.reconstructed] as number[],
    low = Math.min(0, ...values),
    high = Math.max(0.05, ...values) * 1.08,
    x = (k: number) => 55 + (k * 470) / Math.max(1, p.bands.length - 1),
    y = (v: number) => 210 - ((v - low) / (high - low)) * 175;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 580 255");
  svg.setAttribute("role", "img");
  svg.setAttribute(
    "aria-label",
    "Observed and reconstructed physical reflectance",
  );
  function element(
    tag: string,
    attributes: Record<string, string | number>,
    text?: string,
  ) {
    const node = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attributes))
      node.setAttribute(k, String(v));
    if (text) node.textContent = text;
    svg.append(node);
  }
  for (let k = 0; k <= 4; k++) {
    const v = low + ((high - low) * k) / 4;
    element("path", { d: `M50 ${y(v)}H535`, stroke: "#dce5e9" });
    element(
      "text",
      {
        x: 43,
        y: y(v) + 4,
        "text-anchor": "end",
        "font-size": 10,
        fill: "#506b7c",
      },
      v.toFixed(2),
    );
  }
  element(
    "text",
    { x: 55, y: 16, "font-size": 11, fill: "#35566e" },
    "Reflectance (1) · blue points: observed · amber line: reconstructed",
  );
  element("polyline", {
    points: p.reconstructed.map((v, k) => `${x(k)},${y(v!)}`).join(" "),
    fill: "none",
    stroke: "#b97a29",
    "stroke-width": 2,
  });
  p.observed.forEach((v, k) => {
    element("circle", { cx: x(k), cy: y(v!), r: 4, fill: "#254e71" });
    element(
      "text",
      {
        x: x(k),
        y: 235,
        "text-anchor": "middle",
        "font-size": 11,
        fill: "#35566e",
      },
      p.bands[k],
    );
  });
  $("spectrum").replaceChildren(svg);
}
$("load").onclick = () =>
  void loadParent()
    .then(() =>
      status(
        "Source inventory loaded. Select the fit acquisition and parameters.",
      ),
    )
    .catch(fail);
$("form").onsubmit = (event) => {
  event.preventDefault();
  void (async () => {
    busy(true);
    try {
      const spec = { kind: "spectral", spectral: recipe() },
        fingerprint = JSON.stringify(spec);
      let pending: { fingerprint: string; key: string } | undefined;
      try {
        pending =
          JSON.parse(
            localStorage.getItem("rslib.pending-spectral") || "null",
          ) ?? undefined;
      } catch {}
      const key =
        pending?.fingerprint === fingerprint
          ? pending.key
          : crypto.randomUUID();
      localStorage.setItem(
        "rslib.pending-spectral",
        JSON.stringify({ fingerprint, key }),
      );
      const job = await api<Job>("/api/jobs", { ...spec, request_key: key });
      localStorage.removeItem("rslib.pending-spectral");
      await follow(job.id);
    } catch (error) {
      busy(false);
      fail(error);
    }
  })();
};
$("cancel").onclick = () => {
  if (active) void api(`/api/jobs/${active.id}/cancel`, {}).catch(fail);
};
$("retry").onclick = () => {
  if (active)
    void api<Job>(`/api/jobs/${active.id}/retry`, {})
      .then((j) => follow(j.id, true))
      .catch(fail);
};
$("reconnect").onclick = () => {
  if (activeId) void follow(activeId, true);
};
$("refresh-history").onclick = () => void historyList().catch(fail);
$("extra-display").onchange = extra;
$("loading-component").onchange = loadings;
const query = new URLSearchParams(location.search);
void historyList().catch(fail);
if (query.has("job")) void follow(query.get("job")!, true);
else if (query.has("run")) {
  input("run-id").value = query.get("run")!;
  void loadParent().catch(fail);
}
