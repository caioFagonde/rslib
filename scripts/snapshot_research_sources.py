"""Snapshot primary repository/model-card metadata; never download or execute weights."""

import argparse
import concurrent.futures
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPOSITORIES = [
    "ucam-eo/tessera",
    "zhu-xlab/Copernicus-FM",
    "facebookresearch/dinov3",
    "IBM/terramind",
    "NASA-IMPACT/Prithvi-EO-2.0",
    "nasaharvest/galileo",
    "nasaharvest/presto",
    "gastruc/AnySat",
    "gastruc/UniverSat",
    "Clay-foundation/model",
    "allenai/olmoearth_pretrain",
    "allenai/satlaspretrain_models",
    "zhu-xlab/DOFA",
    "AABNassim/spectral_earth",
    "WHU-Sigma/HyperSIGMA",
    "likyoo/open-cd",
    "opengeos/segment-geospatial",
    "ChenDelong1999/RemoteCLIP",
    "jgomezdans/prosail",
    "robintw/Py6S",
    "Christiaanvandertol/SCOPE",
    "eradiate/eradiate",
    "isofit/isofit",
    "hectornieto/pyTSEB",
    "hectornieto/pyDMS",
    "DHI-GRAS/pywapor",
    "isce-framework/isce3",
    "insarlab/MintPy",
    "johntruckenbrodt/pyroSAR",
    "langnico/global-canopy-height-model",
    "acolite/acolite",
    "usask-arg/sasktran2",
    "markusfoote/mag1c",
    "kvos/CoastSat",
    "OGGM/oggm",
    "GlacioHack/xdem",
    "PDAL/PDAL",
    "nasa/EMIT-Data-Resources",
    "NASA-IMPACT/Prithvi-WxC",
    "microsoft/aurora",
    "GERSL/pycold",
    "nasaharvest/cropharvest",
    "ESAOpenSR/SEN2SR",
    "ESAOpenSR/opensr-model",
    "PatrickTUM/UnCRtainTS",
    "Ly403/EMRDM",
    "tangkai-RS/AnytimeFormer",
    "kang-wu/SkySensePlusPlus",
    "VMarsocci/pangaea-bench",
    "FM4CS/THOR",
    "gsumbul/SMARTIES",
    "cloudsen12/models",
    "sentinel-hub/sentinel2-cloud-detector",
]
MODELS = [
    "ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL",
    "ibm-esa-geospatial/TerraMind-1.0-tiny",
    "nasaharvest/galileo",
    "g-astruc/UniverSat",
    "allenai/OlmoEarth-v1_2-Nano",
    "geotessera/TESSERA-V-2.0-2B-N",
    "geotessera/TESSERA-V-2.0-2B-M",
    "wangyi111/Copernicus-FM",
    "tacofoundation/SEN2SR",
]


def fetch(url):
    try:
        with urlopen(
            Request(
                url, headers={"User-Agent": "rslib-research/0.1", "Accept": "application/json"}
            ),
            timeout=20,
        ) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                return {"url": url, "error": "metadata exceeds size budget"}
            return {
                "url": url,
                "http_status": response.status,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "json": json.loads(raw),
            }
    except (HTTPError, OSError, ValueError) as exc:
        return {"url": url, "error": type(exc).__name__, "http_status": getattr(exc, "code", None)}


def repository(name):
    result = fetch("https://api.github.com/repos/" + name)
    value = result.pop("json", {})
    return {
        "requested_repository": name,
        **result,
        "repository": value.get("full_name"),
        "default_branch": value.get("default_branch"),
        "pushed_at": value.get("pushed_at"),
        "archived": value.get("archived"),
        "license_spdx": (value.get("license") or {}).get("spdx_id"),
        "license_name": (value.get("license") or {}).get("name"),
        "license_url": (value.get("license") or {}).get("url"),
        "description": value.get("description"),
    }


def model(name):
    result = fetch("https://huggingface.co/api/models/" + name)
    value = result.pop("json", {})
    return {
        "requested_model": name,
        **result,
        "id": value.get("id"),
        "revision": value.get("sha"),
        "gated": value.get("gated"),
        "card_data": value.get("cardData"),
        "files": [file["rfilename"] for file in value.get("siblings", [])],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refetch repository metadata instead of reusing dated cached responses",
    )
    args = parser.parse_args()
    path = Path("docs/research/source-snapshot.json")
    previous = json.loads(path.read_text()) if path.exists() else {}
    cached = {
        entry["requested_repository"]: {
            "metadata_checked_utc": previous.get("checked_utc"),
            **entry,
        }
        for entry in previous.get("repositories", [])
    }

    def current_repository(name):
        entry = cached.get(name)
        if entry and entry.get("http_status") == 200 and not args.refresh:
            return entry
        return {"metadata_checked_utc": datetime.now(UTC).isoformat(), **repository(name)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        repositories = list(pool.map(current_repository, REPOSITORIES))
        models = list(pool.map(model, MODELS))
    result = {
        "checked_utc": datetime.now(UTC).isoformat(),
        "scope": "Primary metadata snapshot only; a repository license does not establish checkpoint or training-data rights. Availability is checked, executable correctness is not.",
        "repositories": repositories,
        "models": models,
    }
    Path("docs/research/source-snapshot.json").write_text(json.dumps(result, indent=2) + "\n")
    for entry in repositories:
        print(
            entry["requested_repository"],
            entry.get("http_status"),
            entry.get("repository"),
            entry.get("license_spdx"),
        )
    for entry in models:
        print(
            entry["requested_model"],
            entry.get("http_status"),
            (entry.get("card_data") or {}).get("license"),
        )
