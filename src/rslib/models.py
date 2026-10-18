from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BBox(BaseModel):
    """A non-antimeridian WGS84 AOI. Coordinates always use longitude, latitude."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-85, le=85)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-85, le=85)

    @model_validator(mode="after")
    def ordered(self) -> BBox:
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("AOI must have positive width/height; split antimeridian AOIs first")
        return self

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.west, self.south, self.east, self.north


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["earth-search", "planetary-computer"] = "earth-search"
    collections: list[str] = Field(
        default_factory=lambda: ["sentinel-2-c1-l2a"], min_length=1, max_length=8
    )
    bbox: BBox
    datetime: str | None = None
    max_cloud: float | None = Field(default=30, ge=0, le=100)
    max_items: int = Field(default=30, ge=1, le=200)
    max_pages: int = Field(default=10, ge=1, le=30)

    @model_validator(mode="after")
    def provider_default(self) -> Search:
        if "collections" not in self.model_fields_set and self.provider == "planetary-computer":
            self.collections = ["sentinel-2-l2a"]
        return self

    @field_validator("collections")
    @classmethod
    def collection_names(cls, values: list[str]) -> list[str]:
        if any(not v or len(v) > 120 or "/" in v or ".." in v for v in values):
            raise ValueError("Invalid collection ID")
        return values

    @field_validator("datetime")
    @classmethod
    def valid_interval(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.split("/")
        if len(parts) > 2 or value in ("", "../.."):
            raise ValueError("Use an ISO date or start/end interval")
        if len(parts) == 1 and len(parts[0]) == 10:
            parts = [parts[0], parts[0]]
        dates, normalized = [], []
        for index, p in enumerate(parts):
            if p == "..":
                normalized.append(p)
                continue
            date = datetime.fromisoformat(p.replace("Z", "+00:00"))
            if len(p) == 10:
                date = datetime.combine(date.date(), time.max if index == 1 else time.min)
            date = date.replace(tzinfo=UTC) if date.tzinfo is None else date.astimezone(UTC)
            dates.append(date)
            normalized.append(date.isoformat().replace("+00:00", "Z"))
        if len(dates) == 2 and dates[0] > dates[1]:
            raise ValueError("Start must precede end")
        return "/".join(normalized)


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["demo", "earth-search", "planetary-computer"] = "demo"
    collection: str = Field(default="rslib-demo", pattern=r"^[\w.-]{1,120}$")
    item_id: str = Field(default="demo-2026-07-18", pattern=r"^[\w.:-]{1,200}$")
    bbox: BBox = Field(
        default_factory=lambda: BBox(west=-44.75, south=-22.5, east=-44.55, north=-22.3)
    )
    index: Literal["ndvi", "ndmi", "nbr", "evi", "rgb"] = "ndvi"
    size: int = Field(default=512, ge=64, le=1024)
    cloud_buffer: int = Field(default=1, ge=0, le=8)
