"""Existing business contracts plus an explicit local ducking draft preview."""

from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from app.api.v1.models import Uuid
from app.api.v1.projects_models import BusinessModel, SafeInteger


class TimingRequest(BusinessModel):
    shot_revision_id: Uuid
    speech_revision_ids: list[Uuid] = Field(max_length=1000)
    before_ms: SafeInteger
    after_ms: SafeInteger


class TimingResult(BusinessModel):
    required_ms: SafeInteger
    planned_ms: SafeInteger
    shortage_ms: SafeInteger
    method: Literal["measured", "estimated"]
    suitable: bool


class VideoReadiness(BusinessModel):
    shot_revision_id: Uuid
    speech_revision_ids: list[Uuid] = Field(max_length=1000)
    capability_id: Uuid
    path: Literal["research", "production"]


class ReadinessResult(BusinessModel):
    ready: bool
    blockers: list[str] = Field(max_length=1000)
    warnings: list[str] = Field(max_length=1000)


class RightEvidence(BusinessModel):
    id: Uuid
    media_id: Uuid
    source: str = Field(min_length=1, max_length=2000)
    use: str = Field(min_length=1, max_length=2000)
    evidence_media_ids: list[Uuid] = Field(max_length=1000)
    state: Literal["unverified", "verified", "recheck"]
    explanation: str = Field(max_length=4000)

    @model_validator(mode="after")
    def meaningful_fields(self) -> Self:
        if not self.source.strip() or not self.use.strip():
            raise ValueError("Source and use are required")
        if len(self.evidence_media_ids) != len(set(self.evidence_media_ids)):
            raise ValueError("Duplicate evidence")
        return self


class SaveRights(BusinessModel):
    evidence: RightEvidence


class RightsList(BusinessModel):
    items: list[RightEvidence]


class DuckingRequest(BusinessModel):
    timeline_revision_id: Uuid
    music_clip_ids: list[Uuid] = Field(min_length=1, max_length=5000)
    reduction_db: float = Field(ge=0, le=96)
    attack_ms: SafeInteger = Field(le=10000)
    release_ms: SafeInteger = Field(le=10000)


class DuckingResult(BusinessModel):
    timeline: dict[str, JsonValue]
    warnings: list[str] = Field(max_length=1000)
