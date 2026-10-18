"""Render observed QA-masked satellite inputs and measured reference support offline."""

import argparse
import json
from pathlib import Path

import numpy as np
from jinja2 import Environment
from PIL import Image

from rslib.references import audit_references
from rslib.validation import load_verified_run

TEMPLATE = r"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>RSLIB reference cases</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f4f6f7;color:#253b4b;font:14px system-ui,sans-serif}main{max-width:1420px;margin:auto;padding:30px 28px 50px}header{border-bottom:1px solid #c8d2d9;padding-bottom:18px}h1{font-size:28px;font-weight:550;margin:10px 0}h2{font-size:20px;font-weight:550}h3{font-size:15px}p{line-height:1.65;max-width:1000px}a{color:#1a627f}table{border-collapse:collapse;width:100%;font-size:12px}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #d5dce1}th{font-weight:550;color:#506572}button,select{font:inherit;color:inherit;background:white;border:1px solid #9aadb9;border-radius:3px;padding:8px 10px;max-width:100%}button{cursor:pointer;text-align:left}tbody tr.active{background:#e0ecef}tbody tr:hover{background:#eaf0f3}.table-wrap{overflow:auto}.controls{display:grid;grid-template-columns:1fr 2fr;gap:20px;margin:25px 0 20px}label{display:grid;gap:8px;font-size:12px}.maps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}figure{margin:0}figure img{display:block;width:100%;height:285px;object-fit:contain;image-rendering:pixelated;background:#dce2e5;border:1px solid #c0cbd1}figcaption{font-size:12px;line-height:1.6;margin-top:9px}small,.muted{color:#5e707c}.summary{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin:18px 0}.summary section{border-top:1px solid #c8d2d9}.legend{display:flex;gap:16px;flex-wrap:wrap;margin:12px 0;font-size:12px}.swatch{display:inline-block;width:12px;height:12px;vertical-align:middle;margin-right:5px}.support{display:grid;grid-template-columns:90px 1fr 65px;gap:10px;align-items:center;margin:8px 0;font-size:11px}.bar{height:16px;display:flex;background:#b6c1c9}.bar span{display:inline-block;height:100%}.observed{background:#327e79}.estimated{background:#d5a75c}.missing{background:#b6c1c9}code{font-size:11px;overflow-wrap:anywhere}details{border-top:1px solid #c8d2d9;margin-top:20px;padding-top:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px}.notice{border-left:3px solid #a57d3a;padding:8px 14px;background:#f5efdf}@media(max-width:700px){main{padding:18px 14px}.controls,.maps,.summary{grid-template-columns:1fr}figure img{height:260px}h1{font-size:23px}th,td{padding:9px 7px}.support{grid-template-columns:75px 1fr 55px}}@media print{button,select{border:0}details{display:none}figure{break-inside:avoid}}</style>
<main><header><a href="index.html">Development captures</a> · <a href="42-reference-case-audit.json">Audit JSON</a><h1>Satellite reference cases</h1><p>Six small sites, with frozen acquisition recipes and input hashes. Select a site and acquisition to inspect the actual prepared reflectance and retained QA support. Site names describe selection intentions; they are not independently verified land-cover labels.</p><p class="notice">No independent cloud or material labels. These cases exercise input handling and expose coverage failures; they do not establish scientific accuracy.</p></header>
<div class="table-wrap"><table aria-label="Reference case coverage"><thead><tr><th>Site / partition</th><th>Acquisitions</th><th>Saved query missing</th><th>Daily query missing</th><th>Temporal holdout scored</th></tr></thead><tbody id="cases"></tbody></table></div>
<div class="controls"><label>Reference site<select id="case"></select></label><label>Observed acquisition<select id="source"></select></label></div><h2 id="heading"></h2><p id="context" class="muted"></p>
<div class="maps"><figure><img id="rgb" alt="QA-masked observed red green blue reflectance"><figcaption><strong>Observed RGB</strong><br>R/G/B reflectance 0–0.30, fixed linear display. Gray cells have no retained complete spectrum.</figcaption></figure><figure><img id="false" alt="QA-masked observed near infrared shortwave infrared red reflectance"><figcaption><strong>NIR / SWIR1 / red</strong><br>Reflectance 0–0.50, fixed linear display. Colors are a band combination, not material classes.</figcaption></figure><figure><img id="qa" alt="Retained complete spectrum mask"><figcaption><strong>Retained native-QA support</strong><br>Teal: complete retained spectrum. Dark: inside AOI, rejected or unavailable. Light gray: outside AOI.</figcaption></figure></div>
<p id="source-stats"></p><div class="summary"><section><h3>Saved query timeline</h3><p class="muted" id="timeline-note"></p><div class="legend"><span><i class="swatch observed"></i>Observed</span><span><i class="swatch estimated"></i>Estimated</span><span><i class="swatch missing"></i>Missing</span></div><div id="timeline"></div></section><section><h3>Diagnostic coverage</h3><div id="diagnostics"></div><p><a id="open" href="#">Open this run in the local application</a></p><p class="muted">The local service and retained run must be present. This viewer does not execute a job.</p></section></div>
<details><summary>Recipe and frozen input checksums</summary><pre id="recipe"></pre></details><details><summary>Source license records</summary><pre id="licenses"></pre></details><p class="muted">Contains modified Copernicus Sentinel data 2025–2026. Landsat data available from the U.S. Geological Survey. Collection license identifiers and linked legal notices are preserved separately in the audit.</p></main>
<script id="data" type="application/json">{{ report|tojson }}</script><script>
const data=JSON.parse(document.querySelector('#data').textContent), q=s=>document.querySelector(s), pct=x=>x==null?'Not scored':(100*x).toFixed(1)+'%';
let active=0;
function text(selector,value){q(selector).textContent=value}
function choose(index){active=index;q('#case').value=String(index);const c=data.cases[index];q('#source').replaceChildren(...c.sources.map((s,i)=>new Option(s.datetime.slice(0,10)+' · '+s.platform+' · '+pct(s.clear_fraction)+' retained',String(i))));render();}
function render(){const c=data.cases[active],i=Number(q('#source').value),s=c.sources[i];document.querySelectorAll('#cases tr').forEach((row,k)=>row.classList.toggle('active',k===active));text('#heading',c.name+' · '+c.partition);text('#context',c.request.datetime.slice(0,10)+' → '+c.request.datetime.split('/')[1].slice(0,10)+' · '+c.grid.crs+' · '+c.grid.width+' × '+c.grid.height+' cells · '+c.request.resolution+' m · '+c.aoi_cells.toLocaleString()+' AOI cells');['rgb','false','qa'].forEach(type=>q('#'+type).src='42-reference-maps/'+c.id+'/source-'+String(i).padStart(2,'0')+'-'+type+'.png');text('#source-stats',s.id+' · '+s.clear_cells.toLocaleString()+' / '+c.aoi_cells.toLocaleString()+' retained cells ('+pct(s.clear_fraction)+'). NDVI P05 / P50 / P95: '+(s.ndvi_p05_p50_p95?s.ndvi_p05_p50_p95.map(x=>x.toFixed(3)).join(' / '):'unavailable')+'.');text('#timeline-note','Every '+c.request.step_days+' UTC day(s); maximum interpolation bracket '+c.request.max_gap_days+' days. Missing percentages refer to these requested cell dates.');q('#timeline').replaceChildren(...c.query_timeline.map(t=>{const line=document.createElement('div');line.className='support';const date=document.createElement('span');date.textContent=t.day;const bar=document.createElement('div');bar.className='bar';[['observed',t.observed_fraction],['estimated',t.filled_fraction],['missing',Math.max(0,1-t.observed_fraction-t.filled_fraction)]].forEach(([cls,value])=>{const a=document.createElement('span');a.className=cls;a.style.width=100*value+'%';a.title=cls+': '+pct(value);bar.append(a)});const label=document.createElement('span');label.textContent=pct(t.observed_fraction+t.filled_fraction);line.append(date,bar,label);return line}));const h=c.temporal_holdout.summary;const lines=[h?'Whole-date holdout: '+h.scored_cells.toLocaleString()+' / '+h.held_out_clear_cells.toLocaleString()+' clear cell dates scored ('+pct(h.scored_fraction)+').':'Fewer than three acquisition days; temporal holdouts unavailable.',h&&h.scored_cells?'NDVI RMSE: linear '+h.linear.rmse.toFixed(4)+'; paired nearest '+h.nearest.rmse.toFixed(4)+'.':'No admissible withheld-date reconstruction; no RMSE score.',c.sensor_agreement.pairs.length+' disjoint sensor pair(s) accepted within 48 h and at least 100 common-clear cells.','Same interval evaluated every day: '+pct(c.daily_query_diagnostic.unsupported_fraction)+' missing. Saved recipe/output unchanged.',...c.coverage_notes];q('#diagnostics').replaceChildren(...lines.map(value=>{const p=document.createElement('p');p.textContent=value;return p}));text('#recipe',JSON.stringify({request:c.request,input_checksums:c.checks.input_checksums},null,2));text('#licenses',c.checks.source_metadata_captured?JSON.stringify(c.checks.license_records,null,2):'Legacy development input; full source/license metadata were not captured before acquisition.');q('#open').href='http://127.0.0.1:8000/workflows.html?run='+c.run_id;}
data.cases.forEach((c,i)=>{q('#case').add(new Option(c.name,String(i)));const tr=document.createElement('tr');const td=document.createElement('td');const button=document.createElement('button');button.textContent=c.name+' / '+c.partition;button.onclick=()=>choose(i);td.append(button);tr.append(td);[c.sources.length,pct(c.query_support.unsupported_fraction),pct(c.daily_query_diagnostic.unsupported_fraction),pct(c.temporal_holdout.summary?.scored_fraction)].forEach(value=>{const cell=document.createElement('td');cell.textContent=String(value);tr.append(cell)});q('#cases').append(tr)});q('#case').onchange=()=>choose(Number(q('#case').value));q('#source').onchange=render;choose(0);
</script></html>"""


def export(catalog: Path, data: Path, output: Path):
    report = audit_references(catalog, data)
    output.mkdir(parents=True, exist_ok=True)
    (output / "42-reference-case-audit.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    for case in report["cases"]:
        stack, _, _ = load_verified_run(data / "runs" / case["run_id"])
        inside = stack.analysis_mask()
        directory = output / "42-reference-maps" / case["id"]
        directory.mkdir(parents=True, exist_ok=True)
        for i, values in enumerate(stack.values):
            valid = np.isfinite(values).all(axis=0) & inside
            for kind, bands, ceiling in [
                ("rgb", ("red", "green", "blue"), 0.3),
                ("false", ("nir", "swir16", "red"), 0.5),
            ]:
                image = np.moveaxis(values[[stack.bands.index(b) for b in bands]], 0, -1)
                scaled = np.rint(np.nan_to_num(np.clip(image / ceiling, 0, 1)) * 255).astype(
                    "uint8"
                )
                scaled[~valid] = [220, 226, 229]
                Image.fromarray(scaled).save(directory / f"source-{i:02d}-{kind}.png")
            qa = np.full((*inside.shape, 3), [220, 226, 229], dtype="uint8")
            qa[inside] = [42, 60, 73]
            qa[valid] = [50, 126, 121]
            Image.fromarray(qa).save(directory / f"source-{i:02d}-qa.png")
    html = Environment(autoescape=True).from_string(TEMPLATE).render(report=report)
    (output / "reference-cases.html").write_text(html)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=Path("docs/reference-projects/catalog.json")
    )
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("docs/showcase"))
    args = parser.parse_args()
    export(args.catalog, args.data, args.output)
