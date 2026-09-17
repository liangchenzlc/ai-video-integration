from typing import Literal

from pydantic import Field

from app.api.v1.models import Uuid
from app.api.v1.projects_models import BusinessModel, PositiveInteger


class ConfigureTools(BusinessModel):
    ffmpeg_grant_id: Uuid


class ImportMedia(BusinessModel):
    file_grant_id: Uuid
    purpose: Literal["reference", "speech", "video", "music", "sfx", "evidence"]


class RelocateMedia(BusinessModel):
    file_grant_id: Uuid
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CancelJob(BusinessModel):
    reason: str = Field(min_length=1, max_length=500)


class Media(BusinessModel):
    id: Uuid
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: PositiveInteger
    mime: Literal["image/png", "image/jpeg", "video/mp4", "audio/wav", "audio/mpeg", "audio/mp4"]
    duration_ms: PositiveInteger | None
    width: PositiveInteger | None
    height: PositiveInteger | None
    availability: Literal["staging", "available", "missing", "quarantined"]
    provenance: Literal["imported", "generated", "derived", "synthetic"]


class MediaPage(BusinessModel):
    items: list[Media] = Field(max_length=200)
    next_cursor: Uuid | None


class Job(BusinessModel):
    id: Uuid
    kind: Literal[
        "import", "probe", "animatic", "export", "diagnostic", "local_check", "connection_check"
    ]
    state: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    progress: float = Field(ge=0, le=1)
    result_id: Uuid | None
    error_code: str | None = Field(max_length=100)
