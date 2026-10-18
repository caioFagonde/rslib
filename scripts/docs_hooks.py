"""Make archived application links explicit local-app links in the published docs."""

from pathlib import Path


def on_post_build(config):
    for path in (Path(config["site_dir"]) / "showcase").glob("*.html"):
        html = path.read_text()
        for target in ["/workflows.html", "/spectral.html", "/"]:
            html = html.replace(f'href="{target}"', f'href="http://127.0.0.1:8000{target}"')
        path.write_text(html)
