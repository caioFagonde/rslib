# Reference projects

[catalog.json](catalog.json) freezes six small actual-satellite runs: their prepared input hashes, acquisition inventories, recipes, grids and development/holdout roles. The [interactive case viewer](../showcase/reference-cases.html) shows each acquisition's prepared RGB, false-color reflectance and retained native-QA support. The [audit JSON](../showcase/42-reference-case-audit.json) includes the numerical diagnostics. Prepared raster arrays remain local under `data/runs/`.

These are engineering regression cases, not a completed accuracy benchmark. No independent cloud or material labels are attached. Site names and regimes describe selection intentions rather than verified land-cover classes.

## Retained cases

| Site | Partition | Acquisitions | Saved query missing | Daily query missing |
| --- | --- | ---: | ---: | ---: |
| Itatiaia, Brazil | Development | 6 | 26.66% | 26.66% |
| Ames, Iowa | Development | 4 | 100.00% | 94.17% |
| Las Vegas | Development | 4 | 66.67% | 60.08% |
| Santos estuary, Brazil | Holdout | 4 | 79.33% | 75.64% |
| Tromso, Norway | Holdout | 4 | 100.00% | 98.39% |
| Manaus, Brazil | Holdout | 4 | 99.92% | 99.71% |

The five new cases use 30 m grids, two scenes per sensor, a 60 m cloud buffer, 90% clear-support threshold and a 20-day interpolation bracket. The bounded search includes scene-wide cloud percentages up to 100%; native QA determines retained AOI support. Both accepted and rejected acquisitions remain in the record.

“Saved query missing” uses the saved query step, which is five days for the new cases. “Daily query missing” evaluates the same inputs, interval and gap limit every UTC day without modifying the saved recipe. The crop and snow cases demonstrate why a sparse query grid can miss actual observed days. Clear source pixels do not guarantee temporal reconstruction: long brackets and extrapolation stay missing. The Manaus case retains very little clear support; no unmasked fallback is used. Current Sentinel-2 clear classes exclude snow/ice, so this suite does not validate snow retrieval.

## Select, acquire and freeze

[selection-plan.json](selection-plan.json) records the five new site/partition choices before raster processing. Its original SHA256 is `841381c62016242b16e436e11c2f504b45f0d1a1568b634f0fe65f5a3d9ff01b`. Development and holdout cases must use disjoint site groups and nonoverlapping AOIs. Catalog checks also reject exact shared source IDs across partitions. This does not prove geographic independence beyond the declared groups/AOIs or identify every alias of an acquisition across catalogs.

For a new reference campaign, write a new selection plan and case IDs. The acquisition command freezes unsigned full STAC items, collection documents, the selection plan and their hashes before reading imagery:

```bash
uv run rslib reference-acquire seasonal-crops \
  --plan docs/reference-projects/selection-plan.json \
  --snapshots docs/reference-projects/snapshots --data data
uv run rslib reference-register \
  docs/reference-projects/snapshots/seasonal-crops/snapshot.json
```

Interrupted acquisition reuses its pinned inventory and prepared scene caches. A published snapshot is verified rather than replaced. Changed plans, inventories, inputs or licenses fail explicitly. `scripts/acquire_reference_suite.py` runs and registers all selected cases; it requires live network access and is not part of CI.

The committed metadata do not include the prepared rasters. A fresh checkout cannot verify these local runs until their exact artifacts are restored. To reacquire from public assets, use a separate capture directory/catalog and review the new hashes: upstream files and installed implementations may differ, and output bytes are not promised to reproduce the old SHA256. Do not silently replace the published expectations.

## Verify and diagnose

```bash
uv run rslib reference-check seasonal-crops \
  --catalog docs/reference-projects/catalog.json --data data
uv run rslib reference-audit --output data/reference-audit.json
uv run python scripts/export_reference_showcase.py
```

Verification reads local files, checks the published stack and frozen manifest hashes, and matches the recipe, grid, bands, source inventory and observed/synthetic status. New captures also verify the original selection role and every retained source document. The audit measures per-acquisition clear support, saved/daily query support, whole-UTC-date reconstruction holdouts and disjoint near-coincident sensor pairs. Missing/insufficient comparisons remain explicit; no acceptance threshold is fitted to the holdout cases. `accuracy_validated` remains false.

## Source and label rights

The new captures retain the collection's exact license identifier, license links and provider records. Both collection documents currently say `proprietary`; the Landsat link is titled “Public Domain,” and Sentinel links to its legal notice. These declarations are preserved rather than rewritten as an inferred SPDX license.

USGS states that [Landsat cloud data remain public domain](https://www.usgs.gov/faqs/are-landsat-data-cloud-still-considered-be-within-public-domain). The [Copernicus Sentinel legal notice](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice) specifies use and attribution for original and modified data. The viewer identifies modified Copernicus Sentinel data and credits USGS. No source raster distribution bundle is published here. The older Itatiaia case lacks a pre-acquisition full source/license capture and remains development-only.

Independent labels require a separate version, provenance, spatial/temporal correspondence and license record. [CloudSEN12+](https://huggingface.co/datasets/tacofoundation/cloudsen12) is a candidate for expert cloud/shadow labels; its dataset card distinguishes high-quality, scribble and unlabeled patches and identifies a CC0 release. No patch or label from it has been acquired, aligned or scored in this delivery. Native SCL or another model's output must not be relabeled as independent truth.

The offline engineering tests use explicitly synthetic arrays/numerical references, queue/recovery fixtures and HTTP mocks. They exercise implementation contracts and do not supply field accuracy labels.
