"""Portable spectral previews and a printable report; display stretches are explicit."""

from pathlib import Path

import numpy as np
from jinja2 import Environment
from PIL import Image


def previews(directory: Path, observed, scores, abundance, rmse, bands):
    valid = np.isfinite(rmse)
    displays = []

    def save(name, title, values, low, high, description):
        scaled = np.clip(
            (values - low[:, None, None]) / np.maximum(high - low, 1e-12)[:, None, None], 0, 1
        )
        rgba = np.concatenate((np.nan_to_num(scaled), valid[None]), axis=0)
        Image.fromarray(np.rint(np.moveaxis(rgba, 0, -1) * 255).astype("uint8")).save(
            directory / name
        )
        displays.append(
            {
                "filename": name,
                "title": title,
                "description": description,
                "minimum": low.tolist(),
                "maximum": high.tolist(),
            }
        )

    def stretch(values):
        return np.nanpercentile(values[:, valid], [2, 98], axis=1)

    rgb = np.moveaxis(observed, -1, 0)[[bands.index(b) for b in ("red", "green", "blue")]]
    save(
        "rgb.png",
        "Observed RGB",
        rgb,
        *stretch(rgb),
        "R/G/B, independent P02–P98 display stretches; physical reflectance is preserved in the source.",
    )
    pc = np.moveaxis(scores, -1, 0)
    if len(pc) < 3:
        pc_rgb = np.repeat(pc[:1], 3, axis=0)
        description = (
            "PC1 grayscale, P02–P98 display stretch. Select individual components for other scores."
        )
    else:
        pc_rgb = pc[:3]
        description = (
            "PC1/PC2/PC3 in R/G/B, independent P02–P98 stretches. Colors have no material meaning."
        )
    save("pca.png", "PCA overview", pc_rgb, *stretch(pc_rgb), description)
    fractions = np.moveaxis(abundance, -1, 0)
    frac_rgb = np.zeros((3, *rmse.shape))
    frac_rgb[: min(3, len(fractions))] = fractions[:3]
    save(
        "abundance.png",
        "Spectral fractions overview",
        frac_rgb,
        np.zeros(3),
        np.ones(3),
        "E1/E2/E3 in R/G/B, 0–1. Additional endmembers are available individually; components are not assigned material names.",
    )
    error = np.repeat(rmse[None], 3, axis=0)
    ceiling = float(np.nanpercentile(rmse, 98))
    save(
        "rmse.png",
        "Reconstruction RMSE",
        error,
        np.zeros(3),
        np.full(3, ceiling),
        "Reflectance RMSE; black=0, white=scene P98. Display clips; inspector values remain unclipped.",
    )
    for i, layer in enumerate(pc):
        image = np.repeat(layer[None], 3, axis=0)
        save(
            f"pc-{i + 1:02d}.png",
            f"PC{i + 1}",
            image,
            *stretch(image),
            "Dimensionless covariance-PCA score; grayscale P02–P98 display stretch.",
        )
    for i, layer in enumerate(fractions):
        save(
            f"endmember-{i + 1:02d}.png",
            f"Endmember {i + 1} fraction",
            np.repeat(layer[None], 3, axis=0),
            np.zeros(3),
            np.ones(3),
            "Black=0, white=1; fraction conditional on the selected geometric library, not validated material abundance.",
        )
    return displays


TEMPLATE = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Spectral analysis report</title>
<style>body{font:14px system-ui;color:#243a4d;max-width:1200px;margin:30px auto;padding:0 20px}h1{font-size:26px}h2{font-size:19px;margin-top:28px}p,li{line-height:1.6}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f3f5;padding:14px;font-size:12px}table{border-collapse:collapse;width:100%;font-size:12px}td,th{padding:8px;border-bottom:1px solid #ccd6dd;text-align:left}.maps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}figure{margin:0}img{width:100%;image-rendering:pixelated;background:#e1e6e9}figcaption{font-size:11px;line-height:1.5}a{color:#245e8a}@media(max-width:700px){.maps{grid-template-columns:1fr 1fr}}@media print{body{margin:0}a{color:inherit}pre{font-size:9px}figure{break-inside:avoid}}</style>
<h1>Spectral analysis report</h1><p>{{ 'Synthetic fixture' if r.synthetic else 'Satellite observations' }} · {{ r.source.id }} · {{ r.source.datetime }}</p>
<p>{{ r.grid.crs }} · {{ r.grid.width }} × {{ r.grid.height }} cells · {{ r.fcls.valid_cells }} complete QA-valid observed spectra. This is an exploratory scene fit; material fractions have no independent validation.</p>
<div class="maps">{% for d in r.displays[:4] %}<figure><img src="{{ d.filename }}" alt="{{ d.title }}"><figcaption><strong>{{ d.title }}</strong><br>{{ d.description }}<br>Display minima {{ d.minimum }}; maxima {{ d.maximum }}.</figcaption></figure>{% endfor %}</div>
<h2>Fit and source endmembers</h2><p>Median reflectance reconstruction RMSE {{ '%.6f'|format(r.fcls.rmse_median) }}; P95 {{ '%.6f'|format(r.fcls.rmse_p95) }}. Maximum convex optimality gap {{ r.fcls.maximum_optimality_gap }} reflectance².</p>
<table><thead><tr><th>Component</th><th>Row, column</th><th>Observed source spectrum</th><th>Projected endmember spectrum</th></tr></thead><tbody>{% for cell in r.vca.cells %}<tr><td>E{{ loop.index }}</td><td>{{ cell.row }}, {{ cell.column }}</td><td>{{ r.vca.observed_spectra[loop.index0] }}</td><td>{{ r.vca.projected_endmembers[loop.index0] }}</td></tr>{% endfor %}</tbody></table><p>Band order: {{ r.vca.bands|join(', ') }}. PCA retained variance: {{ r.pca.variance_fraction }}. Projection: {{ r.vca.projection }}; seed {{ r.vca.seed }}.</p>
<h2>Parent monitoring project</h2><p>Run {{ r.run_id }}. The following temporal coverage describes the parent monitoring run, not this single-acquisition fit.</p><pre>{{ r.parent.summary|tojson(indent=2) }}</pre>
<p>Observed support, estimated support and missing support remain distinct. Native QA excludes source pixels before preparation. No interpolated spectra enter this fit.</p><ul>{% for note in r.parent.coverage_notes %}<li>{{ note }}</li>{% endfor %}</ul>
{% if r.parent.fields %}<h2>Monitoring areas</h2><table><tr><th>Area</th><th>Projected area (m²)</th><th>Fixed observed area (m²)</th></tr>{% for field in r.parent.fields %}<tr><td>{{ field.name }}</td><td>{{ field.area_m2 }}</td><td>{{ field.fixed_observed_area_m2 }}</td></tr>{% endfor %}</table>{% endif %}
<h2>Assumptions and limitations</h2><ul>{% for note in r.limitations + r.parent.limitations %}<li>{{ note }}</li>{% endfor %}</ul>
<h2>Reproduction</h2><p><a href="request.json">Saved job request</a> · <a href="report.json">Full coefficients, source provenance and checksums</a> · <a href="bundle.zip">Download report and artifacts</a></p><p>With the pinned source run installed under the same ID: <code>rslib jobs submit --spec request.json --data data</code>. Start <code>rslib serve</code> to process the queue. Source checksum differences fail explicitly.</p>
<pre>{{ r.recipe|tojson(indent=2) }}</pre><h2>Implementation record</h2><pre>{{ r.implementation|tojson(indent=2) }}</pre><p>Replaying a request uses the installed implementation. Compare these versions and source hashes when reproducing a result across environments.</p><h2>Parent acquisition recipe</h2><pre>{{ r.parent.request|tojson(indent=2) }}</pre><h2>Checksums</h2><pre>{{ r.input_checksums|tojson(indent=2) }}</pre>
<table><tr><th>Artifact</th><th>SHA256</th></tr>{% for o in r.outputs %}<tr><td><a href="{{ o.path }}">{{ o.path }}</a></td><td style="overflow-wrap:anywhere">{{ o.sha256 }}</td></tr>{% endfor %}</table></html>"""


def write_report(directory: Path, report: dict):
    env = Environment(autoescape=True)
    (directory / "report.html").write_text(env.from_string(TEMPLATE).render(r=report))
