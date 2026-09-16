"""Implemented T02-A DTOs. No absolute path is included in renderer-facing results."""

from typing import Annotated, Literal

from pydantic import BeforeValidator, ConfigDict, Field, JsonValue
from pydantic.alias_generators import to_camel

from app.api.v1.models import StrictModel, Uuid, json_integer

type SafeInteger = Annotated[int, BeforeValidator(json_integer), Field(ge=0, le=9007199254740991)]
type PositiveInteger = Annotated[
    int, BeforeValidator(json_integer), Field(ge=1, le=9007199254740991)
]


class BusinessModel(StrictModel):
    model_config = ConfigDict(alias_generator=to_camel)


class Envelope[T](BusinessModel):
    request_id: Uuid
    data: T


class Command[T](BusinessModel):
    client_operation_id: Uuid
    expected_revision: SafeInteger
    payload: T


class GrantPayload(BusinessModel):
    grant_id: Uuid
    path: str = Field(min_length=1, max_length=32767)
    purpose: Literal["createProject", "openProject", "importMedia", "ffmpeg"]
    window_id: PositiveInteger


class Fps(BusinessModel):
    numerator: Annotated[Literal[24, 25, 30], BeforeValidator(json_integer)]
    denominator: Annotated[Literal[1], BeforeValidator(json_integer)]


class CreatePayload(BusinessModel):
    directory_grant_id: Uuid
    name: str = Field(min_length=1, max_length=120)
    aspect: Literal["16:9", "9:16"]
    resolution: Literal["720p", "1080p"]
    fps: Fps
    target_ms: PositiveInteger


class OpenProject(BusinessModel):
    directory_grant_id: Uuid
    requested_mode: Literal["read", "write"]


class MutationReceipt(BusinessModel):
    operation_id: Uuid
    committed_revision: SafeInteger
    resource_id: Uuid
    state: str = Field(min_length=1, max_length=100)


class Project(BusinessModel):
    id: Uuid
    name: str = Field(min_length=1, max_length=120)
    revision: SafeInteger
    event_sequence: SafeInteger
    format_version: PositiveInteger
    aspect: Literal["16:9", "9:16"]
    resolution: Literal["720p", "1080p"]
    fps: Fps
    target_ms: PositiveInteger
    budget_micro_cny: SafeInteger
    saved_at: str | None
    read_only: bool
    execution_mode: Literal["synthetic", "real"] | None = None


class Session(BusinessModel):
    project_id: Uuid
    project_session_id: Uuid
    mode: Literal["read", "write"]
    project: Project


class Operation(BusinessModel):
    operation_id: Uuid
    state: Literal["committed", "accepted"]
    receipt: MutationReceipt


class RecentProject(BusinessModel):
    project_id: Uuid
    name: str = Field(min_length=1, max_length=120)
    last_opened_at: str


class ClosedSession(BusinessModel):
    closed: Literal[True]


class PrivateDirectory(BusinessModel):
    path: str = Field(min_length=1, max_length=32767)


type DraftKind = Literal["story", "asset", "shot", "speech", "subtitle", "timeline", "observation"]


class DraftContent(BusinessModel):
    kind: DraftKind
    content: dict[str, JsonValue]


class SaveDraftPayload(BusinessModel):
    draft_id: Uuid
    artifact_id: Uuid
    base_revision_id: Uuid | None
    content: DraftContent


class Draft(BusinessModel):
    id: Uuid
    artifact_id: Uuid
    base_revision_id: Uuid | None
    content: DraftContent


class DraftSummary(BusinessModel):
    id: Uuid
    artifact_id: Uuid
    kind: DraftKind
    saved_at: str
