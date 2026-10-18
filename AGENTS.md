# RSLIB development

Build a reusable remote-sensing library with a shared browser/TUI analysis core. The Rust hydrology engine is an independent implementation of public TRIGRS reference equations, not a wrapper around an installed model.

Prioritize reliable day-to-day operations: analysis-ready harmonization, multi-sensor stacks, native QA, consistent grids and units, compositing, gap filling, caching and recovery. Model selection and algorithmic novelty serve these practical workflows; do not replace this priority with a frontier-model catalog.

The user explicitly rejected promotional copy and generic AI presentation. Use functional labels, specific methods and measured results. Do not add slogans, sentence fragments in rhetorical pairs/triples, inflated significance, decorative statistics or fabricated imagery placeholders. An analysis interface must support an actual task: inspect values and their sources, assess missing data, change processing choices, and export reproducible results. Job completion does not imply adequate coverage or validated scientific accuracy. Record missing capabilities and acceptance evidence in `docs/PRODUCT_AUDIT.md`; a screenshot or passing unit test does not establish professional readiness.

Preserve the user's request for visible progress: update `docs/showcase` with real captures/figures as substantial features land, and create clearly labeled concept art for major visual design explorations. Keep original generation prompts. Operational screenshots, synthetic fixtures, scientific model scenarios and proposed features must remain distinguishable. Never depict generated concept artwork as a real satellite observation or working feature.

Use explicit units, grids, radiometric calibration, nodata and QA. Do not invent missing geotechnical inputs or interpret SOC stocks as measured emissions. Fail explicitly for unsupported physics and calibration. Keep scientific assumptions and acceptance gates in `docs/SCIENCE.md` and `docs/HYDRO.md`.

Relevant checks: `uv run pytest`; `cargo test --locked --workspace`; `cargo fmt --all -- --check`; `cargo clippy --locked --workspace --all-targets -- -D warnings`; `npm --prefix web run build`. Browser captures are opt-in because they use a local server and public basemap/terrain services. Do not run live source checks as offline unit tests.

Python dependencies use `uv.lock`; Rust uses `Cargo.lock`; browser dependencies use `web/package-lock.json`. After changing Python production dependencies, refresh `requirements.lock` with `uv export --locked --no-dev --extra postgis --no-emit-project --output-file requirements.lock` for Docker. Build browser assets before packaging the Python wheel. Keep runtime data, generated build directories and credentials out of Git.
