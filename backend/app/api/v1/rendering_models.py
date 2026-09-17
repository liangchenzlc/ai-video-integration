"""Renderer-safe timeline editing and frozen render/export contracts."""

from typing import Literal, Self

from pydantic import Field, model_validator

from app.api.v1.models import Uuid
from app.api.v1.projects_models import BusinessModel, Fps, PositiveInteger, SafeInteger


class Keyframe(BusinessModel):
    time_ms: SafeInteger
    property: Literal["x", "y", "scale", "opacity", "volume"]
    value: float = Field(ge=-10000, le=10000, allow_inf_nan=False)
    interpolation: Literal["linear", "hold"]


class Track(BusinessModel):
    id: Uuid
    kind: Literal["image", "video", "voice", "music", "sfx", "subtitle"]
    order: SafeInteger = Field(le=100)
    muted: bool


class Clip(BusinessModel):
    id: Uuid
    track_id: Uuid
    shot_id: Uuid | None
    media_id: Uuid | None
    content_revision_id: Uuid | None
    start_ms: SafeInteger
    in_ms: SafeInteger
    out_ms: PositiveInteger
    duration_ms: PositiveInteger
    gain_db: float = Field(ge=-96, le=12, allow_inf_nan=False)
    linked_clip_ids: list[Uuid] = Field(max_length=1000)
    keyframes: list[Keyframe] = Field(max_length=1000)


class Transition(BusinessModel):
    id: Uuid
    from_clip_id: Uuid
    to_clip_id: Uuid
    type: Literal["cut", "dissolve", "fade"]
    duration_ms: SafeInteger = Field(le=10000)


class TimelinePayload(BusinessModel):
    width: Literal[720, 1080, 1280, 1920]
    height: Literal[720, 1080, 1280, 1920]
    fps: Fps
    duration_ms: PositiveInteger
    tracks: list[Track] = Field(min_length=1, max_length=100)
    clips: list[Clip] = Field(max_length=5000)
    transitions: list[Transition] = Field(max_length=1000)
    burn_subtitles: bool


class RenderAnimatic(BusinessModel):
    timeline_revision_id: Uuid


class RenderPlanPreview(RenderAnimatic):
    burn_subtitles: bool | None = None


class ExportFilm(RenderAnimatic):
    target_grant_id: Uuid
    burn_subtitles: bool
    overwrite_confirmed: bool


class MediaHash(BusinessModel):
    media_id: Uuid
    sha256: str = Field(pattern="^[0-9a-f]{64}$")


class RenderPlan(BusinessModel):
    id: Uuid
    compiler_version: str = Field(min_length=1, max_length=100)
    timeline_revision_id: Uuid
    timeline: TimelinePayload
    media_hashes: list[MediaHash] = Field(max_length=1000)
    input_hash: str = Field(pattern="^[0-9a-f]{64}$")
    video_codec: Literal["h264"]
    audio_codec: Literal["aac"] | None
    purpose: Literal["preview", "animatic", "export"]


class ExportRecord(BusinessModel):
    id: Uuid
    timeline_revision_id: Uuid
    job_id: Uuid
    state: Literal["pending", "complete", "failed", "cancelled"]
    media_id: Uuid | None
    input_hash: str = Field(pattern="^[0-9a-f]{64}$")


class ReplacementPreview(RenderAnimatic):
    clip_id: Uuid
    new_media_id: Uuid


class ReplacementImpact(BusinessModel):
    shortage_ms: SafeInteger
    affected_clip_ids: list[Uuid] = Field(max_length=5000)
    required_checks: list[str] = Field(max_length=100)
    can_preserve_edit: bool


class TimelineEdit(BusinessModel):
    timeline: TimelinePayload
    action: Literal["move", "split", "trim"]
    clip_id: Uuid
    start_ms: SafeInteger | None = None
    split_ms: SafeInteger | None = None
    in_ms: SafeInteger | None = None
    out_ms: PositiveInteger | None = None
    duration_ms: PositiveInteger | None = None

    @model_validator(mode="after")
    def action_fields(self) -> Self:
        if self.action == "move" and self.start_ms is None:
            raise ValueError("Move needs startMs")
        if self.action == "split" and self.split_ms is None:
            raise ValueError("Split needs splitMs")
        if self.action == "trim" and (self.in_ms is None or self.out_ms is None):
            raise ValueError("Trim needs inMs/outMs")
        return self


class SubtitleSplit(BusinessModel):
    clip_id: Uuid
    split_ms: SafeInteger


class TimelineEditResult(BusinessModel):
    timeline: TimelinePayload
    affected_clip_ids: list[Uuid] = Field(max_length=5000)
    subtitle_split_preview: list[SubtitleSplit] = Field(max_length=5000)
