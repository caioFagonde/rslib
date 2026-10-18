"""Bounded, model-supplied segmentation and super-resolution inference."""

from __future__ import annotations

import numpy as np


def predict_tiles(
    model,
    image: np.ndarray,
    *,
    tile_size: int = 256,
    halo: int = 32,
    device: str = "cpu",
    output_scale: int = 1,
    precision: str = "float32",
) -> np.ndarray:
    """Torch model: NCHW -> NCHW, integer spatial scaling; values returned unchanged.

    Halo context is removed on write, so each output pixel is written exactly once.
    Normalization, band order, physical units, receptive field, model licensing and
    training-domain checks belong to the caller's model card. Missing pixels are
    filled with zero for inference and restored to NaN in all output channels.
    """
    import torch

    image = np.asarray(image, dtype="float32")
    if image.ndim != 3 or image.shape[0] < 1 or min(image.shape[1:]) < 1:
        raise ValueError("Expected nonempty CHW image")
    if (
        image.shape[1] * image.shape[2] > 16_777_216
        or not 16 <= tile_size <= 2048
        or not 0 <= halo < tile_size / 2
        or not isinstance(output_scale, int)
        or not 1 <= output_scale <= 8
        or not isinstance(tile_size, int)
        or not isinstance(halo, int)
        or precision not in {"float32", "float16"}
    ):
        raise ValueError("Image/tile budget exceeded or halo too large")
    if precision == "float16" and torch.device(device).type != "cuda":
        raise ValueError("float16 autocast requires CUDA; use float32 on CPU")
    expected_size = tile_size * output_scale
    stride = tile_size - 2 * halo
    valid = np.isfinite(image).all(axis=0)
    source = np.nan_to_num(image, nan=0, posinf=0, neginf=0)
    padded = np.pad(source, ((0, 0), (halo, tile_size), (halo, tile_size)), mode="edge")
    output = None
    training = model.training
    model.to(device)
    model.eval()
    try:
        with (
            torch.inference_mode(),
            torch.autocast(
                device_type=torch.device(device).type,
                dtype=torch.float16,
                enabled=precision == "float16",
            ),
        ):
            for y in range(0, image.shape[1], stride):
                for x in range(0, image.shape[2], stride):
                    patch = torch.from_numpy(
                        np.ascontiguousarray(padded[:, y : y + tile_size, x : x + tile_size])
                    )[None].to(device)
                    prediction = model(patch)
                    if isinstance(prediction, dict):
                        prediction = prediction["out"]
                    if (
                        prediction.ndim != 4
                        or prediction.shape[0] != 1
                        or prediction.shape[1] < 1
                        or tuple(prediction.shape[2:]) != (expected_size, expected_size)
                    ):
                        raise ValueError("Model must return NCHW at the declared output scale")
                    prediction = prediction[0].float().cpu().numpy()
                    if output is None:
                        shape = (prediction.shape[0], *(s * output_scale for s in image.shape[1:]))
                        if np.prod(shape) * 4 > 268_435_456:
                            raise ValueError(
                                "Output exceeds 256 MiB; tile the AOI into separate jobs"
                            )
                        output = np.empty(shape, dtype="float32")
                    h, w = min(stride, image.shape[1] - y), min(stride, image.shape[2] - x)
                    if prediction.shape[0] != output.shape[0] or not np.isfinite(prediction).all():
                        raise ValueError("Model returned inconsistent channels or nonfinite values")
                    s = output_scale
                    output[:, y * s : (y + h) * s, x * s : (x + w) * s] = prediction[
                        :, halo * s : (halo + h) * s, halo * s : (halo + w) * s
                    ]
    finally:
        model.train(training)
    valid = valid.repeat(output_scale, axis=0).repeat(output_scale, axis=1)
    output[:, ~valid] = np.nan
    return output
