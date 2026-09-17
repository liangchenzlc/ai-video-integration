"""Bounded content-workspace contracts. Drafts and adoption reuse existing DTOs."""

from typing import Literal, Self

from pydantic import Field, model_validator

from app.api.v1.models import Uuid
from app.api.v1.projects_models import BusinessModel

type ReferenceRole = Literal[
    "identity",
    "style",
    "location",
    "prop",
    "composition",
    "firstFrame",
    "keyMoment",
    "endFrame",
    "voiceDrive",
    "voiceReference",
]


class ContentDraftSummary(BusinessModel):
    id: Uuid
    artifact_id: Uuid
    kind: Literal["story", "asset", "shot"]
    saved_at: str = Field(min_length=1, max_length=40)


class Storyboard(BusinessModel):
    drafts: list[ContentDraftSummary] = Field(max_length=5000)
    shot_ids: list[Uuid] = Field(max_length=5000)


class Coverage(BusinessModel):
    unassigned_requirement_ids: list[Uuid] = Field(max_length=1000)
    unresolved_requirement_ids: list[Uuid] = Field(max_length=1000)
    invalid_reference_ids: list[Uuid] = Field(max_length=1000)


class ReorderShots(BusinessModel):
    shot_ids: list[Uuid] = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def unique_shots(self) -> Self:
        if len(set(self.shot_ids)) != len(self.shot_ids):
            raise ValueError("Duplicate shot")
        return self


class VerifyReference(BusinessModel):
    draft_id: Uuid
    media_id: Uuid
    role: ReferenceRole
    matches_purpose: bool
    note: str = Field(min_length=1, max_length=2000)


class PromptPreview(BusinessModel):
    template_id: str = Field(min_length=1, max_length=100)
    template_version: str = Field(min_length=1, max_length=100)
    prompt: str = Field(max_length=100000)
    source_revision_ids: list[Uuid] = Field(max_length=1000)
    blockers: list[str] = Field(max_length=100)
    reusable_video_media_id: Uuid | None
