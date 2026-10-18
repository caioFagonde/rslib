# Documentation publishing

The documentation uses MkDocs Material, with dependencies locked in the `docs` dependency group. The site includes workflow guides, scientific contracts, retained reference metadata, validation evidence and actual development captures.

## Preview and validate

```bash
uv sync --locked --only-group docs
uv run --only-group docs mkdocs serve --dev-addr 127.0.0.1:8767
uv run --only-group docs mkdocs build --strict
```

The build writes `site/`, which is excluded from Git. Strict mode fails on missing documentation links. Live satellite acquisition is not part of the documentation build.

## GitHub Pages

`.github/workflows/docs.yml` builds documentation for pull requests. Pushes to `main` and manual dispatches also upload the static artifact and deploy it to the `github-pages` environment. The build has read-only repository permissions; only the deployment job receives `pages: write` and `id-token: write`. Pages must use **GitHub Actions** as its publishing source.

The deployed site is documentation. It does not host the Python service, execute the TUI or acquire satellite imagery. Application links in archived standalone captures are rewritten to the local service during the documentation build. Prepared satellite rasters, local databases and credentials remain outside Git and the Pages artifact.

The documentation workflow follows [GitHub's custom-workflow contract](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages). Do not put service credentials into this static site.
