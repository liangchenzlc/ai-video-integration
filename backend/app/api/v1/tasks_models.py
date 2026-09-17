"""Budgeted tasks use safe integer micro-CNY and explicit, finite recovery actions."""

from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, model_validator

from app.api.v1.models import Uuid
from app.api.v1.projects_models import BusinessModel, PositiveInteger, SafeInteger
from app.api.v1.settings_models import PipelinePhase, ProviderId
from app.storage.drafts import prepare_content
from app.storage.errors import ProjectError

type Stage = Literal["story", "image", "video", "speech", "lipsync", "music", "sfx", "check"]
type ExecutionMode = Literal["synthetic", "real"]
type TaskState = Literal[
    "pending", "running", "complete", "partial", "result_unknown", "pending_download", "failed"
]
type ArtifactKind = Literal[
    "story", "asset", "shot", "speech", "subtitle", "timeline", "observation"
]
type Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Allocation(BusinessModel):
    stage: Stage
    limit_micro_cny: SafeInteger


class SetBudget(BusinessModel):
    total_micro_cny: SafeInteger
    allocations: list[Allocation] = Field(max_length=8)
    warning_percent: Annotated[SafeInteger, Field(ge=1, le=100)]


class Budget(SetBudget):
    execution_mode: ExecutionMode | None


class PlanTask(BusinessModel):
    object_id: Uuid
    stage: Stage
    phase: PipelinePhase
    goal: str = Field(min_length=1, max_length=2000)
    input_revision_ids: list[Uuid] = Field(max_length=1000)
    candidates: Annotated[SafeInteger, Field(ge=1, le=8)]
    include_precheck: bool
    execution_mode: ExecutionMode


class TaskStep(BusinessModel):
    id: Uuid
    purpose: Literal["create", "revise", "precheck"]
    capability_id: Uuid
    max_calls: Annotated[SafeInteger, Field(ge=1, le=16)]
    requested_ms: PositiveInteger | None
    max_micro_cny: SafeInteger
    disclosure: list[Literal["text", "image", "audio", "video", "upload"]] = Field(max_length=5)


class InputPreview(BusinessModel):
    kind: ArtifactKind
    payload: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        try:
            prepare_content({"kind": self.kind, "content": self.payload})
        except ProjectError as error:
            raise ValueError("Invalid task input preview") from error
        return self


class PlannedModel(BusinessModel):
    step_id: Uuid
    provider_id: ProviderId
    model_id: str = Field(min_length=1, max_length=200)
    region: str = Field(min_length=1, max_length=100)
    capability_version: str = Field(min_length=1, max_length=100)


class TaskPlan(BusinessModel):
    id: Uuid
    object_id: Uuid
    stage: Stage
    phase: PipelinePhase
    goal: str = Field(min_length=1, max_length=2000)
    input_revision_ids: list[Uuid] = Field(max_length=1000)
    input_media_hashes: list[Hash] = Field(max_length=1000)
    steps: list[TaskStep] = Field(min_length=1, max_length=32)
    candidates: Annotated[SafeInteger, Field(ge=1, le=8)]
    maximum_micro_cny: SafeInteger
    price_version: str = Field(min_length=1, max_length=100)
    template_version: str = Field(min_length=1, max_length=100)
    expires_at: str = Field(min_length=1, max_length=40)
    execution_mode: ExecutionMode
    input_preview: InputPreview
    models: list[PlannedModel] = Field(min_length=1, max_length=32)


class StartTask(BusinessModel):
    plan_id: Uuid
    authorized_maximum_micro_cny: SafeInteger
    disclosure_accepted: bool


class Task(BusinessModel):
    id: Uuid
    plan_id: Uuid
    state: TaskState
    event_sequence: SafeInteger
    call_ids: list[Uuid] = Field(max_length=1000)
    candidate_revision_ids: list[Uuid] = Field(max_length=1000)
    observation_stopped: bool


class TaskSummary(BusinessModel):
    id: Uuid
    plan_id: Uuid
    object_id: Uuid
    stage: Stage
    phase: PipelinePhase
    state: TaskState
    event_sequence: SafeInteger
    observation_stopped: bool
    active: bool


class TaskPage(BusinessModel):
    items: list[TaskSummary] = Field(max_length=200)
    next_cursor: Uuid | None


class TaskActivity(BusinessModel):
    project_id: Uuid
    project_name: str = Field(min_length=1, max_length=120)
    task_id: Uuid
    state: TaskState


class Call(BusinessModel):
    id: Uuid
    task_id: Uuid
    step_id: Uuid
    submission_token: Uuid
    remote_task_id: str | None = Field(min_length=1, max_length=300)
    state: Literal[
        "prepared",
        "submitting",
        "running",
        "result_unknown",
        "pending_download",
        "succeeded",
        "failed",
        "cancelled",
    ]
    result_media_ids: list[Uuid] = Field(max_length=1000)
    billing_state: Literal["pending", "settled"]
    reserved_micro_cny: SafeInteger
    settled_micro_cny: SafeInteger | None
    expires_at: str | None = Field(min_length=1, max_length=40)
    provider_id: ProviderId
    model_id: str = Field(min_length=1, max_length=200)
    region: str = Field(min_length=1, max_length=100)
    requested_at: str = Field(min_length=1, max_length=40)
    error_code: str | None = Field(min_length=1, max_length=100)


class RecoverCall(BusinessModel):
    action: Literal["query", "download", "stop_waiting", "cancel_remote"]


class ContinueTask(BusinessModel):
    confirmed_unsubmitted_only: bool


class CostSummary(BusinessModel):
    settled_micro_cny: SafeInteger
    reserved_micro_cny: SafeInteger
    remaining_work_micro_cny: SafeInteger
    rework_scenario_micro_cny: SafeInteger
    forecast_micro_cny: SafeInteger
    budget_micro_cny: SafeInteger
    contains_unknown: bool
    estimate_version: str = Field(min_length=1, max_length=100)


class CostEntry(BusinessModel):
    call_id: Uuid
    state: Literal["pending", "settled"]
    reserved_micro_cny: SafeInteger
    settled_micro_cny: SafeInteger | None
    basis: str = Field(max_length=2000)


class CostEntryPage(BusinessModel):
    items: list[CostEntry] = Field(max_length=200)
    next_cursor: Uuid | None


class SettleCall(BusinessModel):
    settled_micro_cny: SafeInteger
    basis: str = Field(min_length=1, max_length=2000)
    evidence_media_ids: list[Uuid] = Field(max_length=1000)
    reason: str = Field(min_length=1, max_length=2000)


class ExternalExpense(BusinessModel):
    expense_id: Uuid
    category: Literal["storage", "transfer", "procurement"]
    state: Literal["estimated", "pending", "settled"]
    amount_micro_cny: SafeInteger
    basis: str = Field(min_length=1, max_length=2000)
