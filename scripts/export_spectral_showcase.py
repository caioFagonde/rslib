"""Build a standalone, interactive figure from actual spectral-analysis COGs.

Run after `rslib spectral-analysis ...`. No imagery is synthesized or fetched.
Displayed RGB/PCA stretches are separate from the physical values inspected.
"""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image

from rslib.validation import load_verified_run

parser = argparse.ArgumentParser()
parser.add_argument("--run", type=Path, default=Path("data/runs/1315d34695e8484093cf6a0ec3cdacad"))
parser.add_argument("--analysis", type=Path, default=Path("data/spectral/20260619-vca"))
args = parser.parse_args()
root = Path("docs/showcase")
report = json.loads((args.analysis / "report.json").read_text())
stack, _, checksums = load_verified_run(args.run)
assert checksums == report["input_checksums"]
for artifact in report["outputs"]:
    assert (
        hashlib.sha256((args.analysis / artifact["path"]).read_bytes()).hexdigest()
        == artifact["sha256"]
    )
assert stack.grid.transform.b == 0 and stack.grid.transform.d == 0
source = stack.values[report["source_index"]]
arrays = {}
for name, path in [
    ("pca", "pca.tif"),
    ("abundance", "abundance.tif"),
    ("rmse", "reconstruction-rmse.tif"),
]:
    with rasterio.open(args.analysis / path) as dataset:
        arrays[name] = dataset.read()
keep = np.isfinite(arrays["rmse"][0])


def stretched(values):
    low, high = np.nanpercentile(values[:, keep], [2, 98], axis=1)
    return np.clip(
        (values - low[:, None, None]) / np.maximum((high - low)[:, None, None], 1e-12), 0, 1
    ), [low.tolist(), high.tolist()]


def png(values):
    rgba = np.concatenate((np.nan_to_num(np.moveaxis(values, 0, -1)), keep[..., None]), axis=-1)
    buffer = io.BytesIO()
    Image.fromarray(np.rint(rgba * 255).astype("uint8"), "RGBA").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


rgb, rgb_stretch = stretched(source[[stack.bands.index(b) for b in ("red", "green", "blue")]])
pca, pca_stretch = stretched(arrays["pca"])
ceiling = float(np.nanpercentile(arrays["rmse"], 98))
error = np.clip(arrays["rmse"][0] / max(ceiling, 1e-12), 0, 1)
# Sequential color ramp; zero dark blue, display ceiling light yellow.
error_rgb = np.stack((0.1 + 0.85 * error, 0.2 + 0.65 * error, 0.4 - 0.2 * error))
payload = {
    "report": report,
    "bands": list(stack.bands),
    "shape": list(keep.shape),
    "valid": keep.ravel().tolist(),
    "spectra": np.moveaxis(source, 0, -1).reshape(-1, len(stack.bands)).astype(float),
    "abundance": np.moveaxis(arrays["abundance"], 0, -1).reshape(-1, 3).astype(float),
    "rmse": arrays["rmse"][0].ravel().astype(float),
    "images": {
        "rgb": png(rgb),
        "pca": png(pca),
        "abundance": png(arrays["abundance"]),
        "rmse": png(error_rgb),
    },
    "display_stretches": {
        "rgb_p02_p98": rgb_stretch,
        "pca_p02_p98": pca_stretch,
        "rmse_p98_ceiling": ceiling,
    },
}
for key in ("spectra", "abundance", "rmse"):
    payload[key] = np.where(np.isfinite(payload[key]), payload[key], None).tolist()
(root / "35-live-spectral-report.json").write_text(
    json.dumps(report, indent=2, allow_nan=False) + "\n"
)
page = r"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Observed-scene spectral analysis · RSLIB</title><style>
*{box-sizing:border-box}body{margin:0;background:#edf1f3;color:#223342;font:14px system-ui,sans-serif}main{max-width:1480px;margin:auto;padding:28px}a{color:#255c87}h1{font-size:26px;margin:14px 0 8px;font-weight:600}h2{font-size:17px;margin:0 0 12px}p{line-height:1.6;margin:8px 0}.source{font:12px ui-monospace,monospace;overflow-wrap:anywhere}.maps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:24px 0 14px}.panel{min-width:0;overflow-wrap:anywhere;background:white;border:1px solid #c6d0d7;padding:15px}.panel h2{font-size:15px}.map{position:relative;background:repeating-conic-gradient(#dce2e6 0 25%,#f4f6f8 0 50%) 50% / 12px 12px;line-height:0}.map img{width:100%;height:auto;image-rendering:pixelated;cursor:crosshair}.cross{position:absolute;border:1px solid #fff;outline:1px solid #182c43;pointer-events:none}.legend{font-size:12px;min-height:56px;color:#526473;line-height:1.6;padding-top:10px}.scale{white-space:nowrap;border-bottom:3px solid #263b4a;width:13.333%;font:10px system-ui;margin:8px 0}.details{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:14px}table{border-collapse:collapse;width:100%;font-size:12px}th,td{text-align:right;padding:8px;border-bottom:1px solid #dde3e8}th:first-child,td:first-child{text-align:left}.stats{color:#4d6474;font-size:13px}.footnote{font-size:12px;color:#516675;margin-top:14px}button{background:white;border:1px solid #647e91;border-radius:3px;padding:8px 12px;color:#244d6c;cursor:pointer}svg{display:block;width:100%;max-height:280px}.cell{font-variant-numeric:tabular-nums}.swatch{display:inline-block;width:10px;height:10px;margin-right:5px}.tag{font-size:11px;letter-spacing:.4px;color:#446275}.curve-key{display:flex;gap:14px;font-size:12px;flex-wrap:wrap}@media(max-width:900px){.maps{grid-template-columns:repeat(2,minmax(0,1fr))}.details{grid-template-columns:minmax(0,1fr)}}@media(max-width:500px){main{padding:14px}.panel{padding:10px}.maps{gap:8px}h1{font-size:22px}.maps h2{min-height:54px}.legend{font-size:11px}.source{font-size:10px}th,td{padding:6px 3px}}
</style><main><a href="index.html">Development captures</a> · <a href="research.html">Reviewed methods</a>
<h1>Observed-scene spectral analysis</h1><p class="tag">COMPUTED FROM SATELLITE OBSERVATIONS · EXPLORATORY SCENE FIT</p>
<p id="source" class="source"></p><p id="summary" class="stats"></p>
<div class="maps">
<section class="panel"><h2>RGB reflectance</h2><div class="map"><img id="rgb" alt="Actual satellite RGB reflectance"><span class="cross"></span></div><div class="scale">300 m</div><div class="legend">R / G / B; each channel stretched to its own scene P02–P98. Checkerboard: excluded or missing.</div></section>
<section class="panel"><h2>PCA components 1 / 2 / 3</h2><div class="map"><img id="pca" alt="Computed PCA component composite"><span class="cross"></span></div><div class="scale">300 m</div><div class="legend" id="variance"></div></section>
<section class="panel"><h2>FCLS spectral fractions</h2><div class="map"><img id="abundance" alt="Computed three-endmember fractions"><span class="cross"></span></div><div class="scale">300 m</div><div class="legend"><span style="color:#ad4239">E1 → red</span> · <span style="color:#39844c">E2 → green</span> · <span style="color:#3c62bd">E3 → blue</span><br>Each channel 0–1; fractions sum to one. No material labels assigned.</div></section>
<section class="panel"><h2>Reflectance reconstruction RMSE</h2><div class="map"><img id="rmse" alt="FCLS reflectance residual"><span class="cross"></span></div><div class="scale">300 m</div><div class="legend" id="error-key"></div></section>
</div><p>Click any raster to inspect that cell. Values below use physical reflectance before display stretching.</p>
<div class="details"><section class="panel"><h2 id="cell-heading">Selected cell</h2><p id="cell" class="cell"></p><div class="curve-key"><span>● Observed spectrum</span><span style="color:#bb7828">— FCLS reconstruction</span></div><div id="spectrum"></div><table><thead><tr><th>Band</th><th>Observed</th><th>Reconstructed</th><th>Residual</th></tr></thead><tbody id="values"></tbody></table></section>
<section class="panel"><h2>Selected geometric endmembers</h2><table><thead><tr><th>Component</th><th>Source cell</th><th>Cell fraction</th></tr></thead><tbody id="members"></tbody></table><p id="fit" class="stats"></p><p class="footnote">VCA: affine branch, centered p−1 dimensions, seed 0. PCA: covariance, no standardization. FCLS: exact small-library simplex-face solver. Native QA and AOI exclusions remain missing; no gap-filled spectra enter the fit.</p><p class="footnote">Geometric extremes can reflect illumination or residual contamination. Fractions and small residuals do not establish physical material abundance. This fit has no independent material validation.</p><button id="download">Download analysis report</button><p class="footnote" id="hash"></p></section></div>
<p class="footnote">North is up. All four rasters share the reported projected grid. Source and output SHA256, coefficients, selected spectra and assumptions are recorded in the analysis report. This page is a standalone computed showcase; execution is available through the library/CLI.</p></main>
<script>const D=__DATA__,$=id=>document.getElementById(id),R=D.report,[H,W]=D.shape,fmt=(v,n=5)=>v===null?'missing':Number(v).toFixed(n);
$('source').textContent=R.source.id+' · '+R.source.datetime;
$('summary').textContent=`${R.grid.crs} · ${W} × ${H} cells · ${R.grid.transform[0]} m · ${R.fcls.valid_cells.toLocaleString()} complete QA-valid spectra · ${D.bands.length} common reflectance bands`;
for(const scale of document.querySelectorAll('.scale'))scale.style.width=(300/(W*R.grid.transform[0])*100)+'%';
$('variance').textContent='Variance: '+R.pca.variance_fraction.map((f,i)=>'PC'+(i+1)+' '+(100*f).toFixed(2)+'%').join(' · ')+'. Each component has its own display stretch; colors have no material meaning.';
$('error-key').textContent='Dark blue: 0 · light yellow: '+fmt(D.display_stretches.rmse_p98_ceiling)+'. Display clips at scene P98; inspected values remain unclipped.';
$('fit').textContent='All valid cells: median RMSE '+fmt(R.fcls.rmse_median)+'; P95 '+fmt(R.fcls.rmse_p95)+'. Maximum convex optimality gap '+R.fcls.maximum_optimality_gap.toExponential(2)+' reflectance².';
$('hash').textContent='Input stack SHA256: '+R.input_checksums['stack.npz'];
function pick(row,col){const i=row*W+col;document.body.dataset.row=row;document.body.dataset.col=col;
for(const cross of document.querySelectorAll('.cross')){cross.style.left=(col/W*100)+'%';cross.style.top=(row/H*100)+'%';cross.style.width=(100/W)+'%';cross.style.height=(100/H)+'%'}
const t=R.grid.transform,e=t[0]*(col+.5)+t[1]*(row+.5)+t[2],n=t[3]*(col+.5)+t[4]*(row+.5)+t[5];
$('cell-heading').textContent=`Cell row ${row}, column ${col}`;
$('members').innerHTML=R.vca.cells.map((p,k)=>`<tr><td>E${k+1}</td><td>${p.row}, ${p.column}</td><td>${D.valid[i]?fmt(D.abundance[i][k]):'missing'}</td></tr>`).join('');
if(!D.valid[i]){$('cell').textContent='Excluded or missing. No fitted fractions at this cell.';$('spectrum').replaceChildren();$('values').replaceChildren();return}
const observed=D.spectra[i],fractions=D.abundance[i],reconstruction=D.bands.map((_,b)=>fractions.reduce((sum,a,k)=>sum+a*R.vca.projected_endmembers[k][b],0));
$('cell').textContent=`Easting ${fmt(e,1)} m · northing ${fmt(n,1)} m · RMSE ${fmt(D.rmse[i])}`;
$('values').innerHTML=D.bands.map((b,k)=>`<tr><td>${b}</td><td>${fmt(observed[k])}</td><td>${fmt(reconstruction[k])}</td><td>${fmt(reconstruction[k]-observed[k])}</td></tr>`).join('');
const lower=Math.min(0,...observed,...reconstruction),upper=Math.max(.05,...observed,...reconstruction)*1.1,xx=k=>60+k*91,yy=v=>205-(v-lower)/(upper-lower)*175;
let svg='<svg viewBox="0 0 580 255" role="img" aria-label="Observed and reconstructed reflectance by band">';
for(let k=0;k<=4;k++){const v=lower+(upper-lower)*k/4,y=yy(v);svg+=`<path d="M55 ${y}H530" stroke="#dce4e8"/><text x="48" y="${y+4}" text-anchor="end" font-size="10" fill="#506778">${v.toFixed(2)}</text>`}
svg+='<text x="15" y="15" fill="#40576a" font-size="11">Reflectance (1)</text><polyline fill="none" stroke="#bb7828" stroke-width="2" points="'+reconstruction.map((v,k)=>xx(k)+','+yy(v)).join(' ')+'"/>';
svg+=observed.map((v,k)=>`<circle cx="${xx(k)}" cy="${yy(v)}" r="4" fill="#284f73"/><text x="${xx(k)}" y="228" text-anchor="middle" font-size="11" fill="#40576a">${D.bands[k]}</text>`).join('');
$('spectrum').innerHTML=svg+'</svg>'}
for(const name of ['rgb','pca','abundance','rmse']){const image=$(name);image.src=D.images[name];image.addEventListener('click',event=>{const box=image.getBoundingClientRect();pick(Math.min(H-1,Math.floor((event.clientY-box.top)/box.height*H)),Math.min(W-1,Math.floor((event.clientX-box.left)/box.width*W)))})}
$('download').addEventListener('click',()=>{const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(R,null,2)],{type:'application/json'}));a.href=url;a.download='spectral-analysis.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});
const first=D.valid.findIndex(Boolean);pick(Math.floor(first/W),first%W);
</script></html>"""
page = page.replace("__DATA__", json.dumps(payload, allow_nan=False).replace("<", "\\u003c"))
(root / "spectral.html").write_text(page)
print("Wrote standalone interactive actual-data figure: docs/showcase/spectral.html")
