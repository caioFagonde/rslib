"""Saved spectral fit parameters and immutable input identity."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rslib.validation import verified_run_metadata

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class SpectralRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    source_index: int = Field(default=0, ge=0, le=100, strict=True)
    components: int = Field(default=3, ge=1, le=6, strict=True)
    endmembers: int = Field(default=3, ge=2, le=6, strict=True)
    projection: Literal["affine", "projective"] = "affine"
    seed: int = Field(default=0, ge=0, le=2**32 - 1, strict=True)
    input_checksums: dict[Literal["stack.npz", "manifest.json"], Digest] | None = None

    @model_validator(mode="after")
    def complete_identity(self):
        if self.input_checksums is not None and set(self.input_checksums) != {
            "stack.npz",
            "manifest.json",
        }:
            raise ValueError("Pin both the stack and manifest checksums")
        return self


def pin_request(data: Path, request: SpectralRequest) -> SpectralRequest:
    report, digests = verified_run_metadata(data / "runs" / request.run_id)
    if request.input_checksums is not None and request.input_checksums != digests:
        raise ValueError("Source run differs from the saved spectral input checksums")
    if request.source_index >= len(report["observations"]):
        raise ValueError("Choose a source index from this run's observation inventory")
    if max(request.components, request.endmembers) > len(report["bands"]):
        raise ValueError("Components and endmembers must not exceed the input band count")
    return request.model_copy(update={"input_checksums": digests})
