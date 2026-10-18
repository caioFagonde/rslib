"""Opt-in, pinned SEN2SRLite adapter. No downloaded Python code is executed."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import httpx
import numpy as np
from affine import Affine

from rslib.deep import predict_tiles
from rslib.raster import Grid

REVISION = "469e9b3a049f9320ba66b3a39b9655dbd31480b3"
MODEL_ID = "SEN2SRLite_NonReference_RGBN_x4"
WEIGHTS = {
    "model.safetensor": "479aa796d5068d0b1206118ccbca27bd3223df0214db1a9b31a1e18349ed1c7e",
    "hard_constraint.safetensor": "fbad981519066387c413ead1d6af7ef3e0d2947c34147ba90163fc79ae539239",
}
BASE_URL = f"https://huggingface.co/tacofoundation/SEN2SR/resolve/{REVISION}/SEN2SRLite/NonReference_RGBN_x4"


def model_card() -> dict:
    return {
        "id": MODEL_ID,
        "revision": REVISION,
        "package": "sen2sr==0.8.5",
        "weights_sha256": dict(WEIGHTS),
        "source": "https://github.com/ESAOpenSR/SEN2SR",
        "weights_license": "cc0-1.0 (upstream model repository card)",
        "bands": ["B04", "B03", "B02", "B08"],
        "input_units": "L2A surface reflectance",
        "input_spacing_m": 10,
        "output_grid_spacing_m": 2.5,
        "scale": 4,
        "tile_size": 128,
        "architecture": "SPAN + Fourier hard constraint",
        "training_domain": "SEN2NAIPv2; transfer to other regions requires evaluation",
        "interpretation": "Model-derived detail; 2.5 m grid is not verified 2.5 m spatial resolution",
    }


def verify_weights(directory: Path) -> None:
    for name, digest in WEIGHTS.items():
        path = directory / name
        if not path.is_file() or path.stat().st_size > 8_388_608:
            raise ValueError(
                f"Missing or oversized {name}; explicitly fetch the registered weights"
            )
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Checkpoint SHA-256 mismatch: {name}")


def fetch_weights(directory: Path) -> dict:
    """Explicit acquisition of two fixed safetensors files, capped at 8 MiB each."""
    directory.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for name, digest in WEIGHTS.items():
            target = directory / name
            if target.is_file() and target.stat().st_size <= 8_388_608:
                if hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                    continue
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=directory, delete=False) as file:
                    temporary = Path(file.name)
                    size, checksum = 0, hashlib.sha256()
                    with client.stream("GET", f"{BASE_URL}/{name}") as response:
                        response.raise_for_status()
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > 8_388_608:
                                raise ValueError("Checkpoint download exceeds registered budget")
                            checksum.update(chunk)
                            file.write(chunk)
                if checksum.hexdigest() != digest:
                    raise ValueError(f"Checkpoint SHA-256 mismatch: {name}")
                os.replace(temporary, target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    verify_weights(directory)
    return model_card()


def load_sen2sr_lite(directory: Path, device: str = "cpu"):
    """Instantiate installed, version-checked architecture and verified local tensors."""
    from importlib.metadata import version

    if version("sen2sr") != "0.8.5":
        raise ValueError("This adapter requires sen2sr==0.8.5")
    verify_weights(directory)
    import torch
    from safetensors.torch import load_file
    from sen2sr.models.opensr_baseline.cnn import CNNSR
    from sen2sr.models.tricks import HardConstraint
    from sen2sr.nonreference import srmodel

    network = CNNSR(4, 4, 24, 4, True, False, 6)
    network.load_state_dict(load_file(directory / "model.safetensor"), strict=True)
    network.eval().requires_grad_(False)
    constraint = HardConstraint(
        low_pass_mask=load_file(directory / "hard_constraint.safetensor")["weights"],
        device=device,
    )

    class StableConstraint(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.inner = inner

        def forward(self, lr, sr):
            # Keep the upstream Fourier correction in float32. Half precision is
            # used for convolutions only, avoiding experimental complex-half FFT.
            with torch.autocast(device_type=sr.device.type, enabled=False):
                return self.inner(lr.float(), sr.float())

    return srmodel(network, StableConstraint(constraint), device).eval()


def superresolve_rgbn(
    model, reflectance: np.ndarray, *, device: str = "cpu", precision: str = "float32"
) -> np.ndarray:
    """CHW calibrated R,G,B,NIR on a native 10 m grid; missing areas stay NaN.

    Supply cloud-masked input. This model does not remove clouds. Unknown context
    is zero-filled during inference; evaluate its influence near masked regions.
    Fourier constraints operate per 128-pixel tile, so halo stitching is approximate.
    """
    if np.ndim(reflectance) != 3 or reflectance.shape[0] != 4:
        raise ValueError("SEN2SRLite requires CHW red, green, blue, NIR reflectance")
    return predict_tiles(
        model,
        reflectance,
        tile_size=128,
        halo=16,
        device=device,
        output_scale=4,
        precision=precision,
    )


def upscale_grid(grid: Grid, scale: int = 4) -> Grid:
    if not isinstance(scale, int) or not 1 <= scale <= 8:
        raise ValueError("Scale must be an integer from 1 to 8")
    return Grid(
        grid.crs, grid.transform * Affine.scale(1 / scale), grid.width * scale, grid.height * scale
    )
