"""Finite immutable-version, adoption and evidence-bearing local-check DTOs."""

from typing import Annotated, Any, Literal, Self

from pydantic import Field, GetJsonSchemaHandler, JsonValue, model_validator
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from app.api.v1.models import Uuid
from app.api.v1.projects_models import BusinessModel, SafeInteger
from app.api.v1.tasks_models import ArtifactKind, Hash
from app.storage.errors import ProjectError
from app.storage.revisions import validate_payload, validator

type RuleId = Annotated[str, Field(min_length=1, max_length=100)]
type SemanticScope = Literal[
    "identityVisual",
    "dialogueAudio",
    "subtitleTiming",
    "referenceInput",
    "requirementCoverage",
    "revealTiming",
    "timelinePlacement",
    "mix",
    "export",
]


class ArtifactState(BusinessModel):
    id: Uuid
    kind: ArtifactKind
    adopted_revision_id: Uuid | None
    confirmed_revision_id: Uuid | None
    needs_update: bool
    latest_adoption_id: Uuid | None


class CompletePayload(BusinessModel):
    kind: ArtifactKind
    content: dict[str, JsonValue]

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        # Export the same finite TypedPayload used for validation. Inline its acyclic
        # definitions so Pydantic does not mistake domain refs for its own registry.
        definitions = validator().schema["$defs"]

        def expand(value: Any) -> Any:
            if isinstance(value, dict):
                if "$ref" in value:
                    return expand(definitions[value["$ref"].removeprefix("#/$defs/")])
                return {key: expand(item) for key, item in value.items()}
            if isinstance(value, list):
                return [expand(item) for item in value]
            return value

        result: JsonSchemaValue = expand(definitions["TypedPayload"])
        return result

    @model_validator(mode="after")
    def complete_content(self) -> Self:
        try:
            validate_payload(self.model_dump(by_alias=True))
        except ProjectError as error:
            raise ValueError("Invalid formal revision") from error
        return self


class Revision(BusinessModel):
    id: Uuid
    artifact_id: Uuid
    parent_id: Uuid | None
    payload: CompletePayload
    content_hash: Hash
    created_at: str = Field(min_length=1, max_length=40)


class RevisionPage(BusinessModel):
    items: list[Revision] = Field(max_length=200)
    next_cursor: Uuid | None


class CreateRevision(BusinessModel):
    draft_id: Uuid


class PreviewAdoption(BusinessModel):
    to_revision_id: Uuid
    expected_revision: SafeInteger


class AdoptRevision(BusinessModel):
    preview_id: Uuid
    to_revision_id: Uuid
    confirm: bool


class ConfirmRevision(BusinessModel):
    revision_id: Uuid
    check_ids: list[Uuid] = Field(min_length=1, max_length=1000)


class UndoAdoption(BusinessModel):
    adoption_id: Uuid


class Impact(BusinessModel):
    preview_id: Uuid
    artifact_id: Uuid
    from_revision_id: Uuid | None
    to_revision_id: Uuid
    affected_artifact_ids: list[Uuid] = Field(max_length=10000)
    affected_scopes: list[SemanticScope] = Field(max_length=9)
    estimated_extra_micro_cny: SafeInteger | None
    required_checks: list[RuleId] = Field(max_length=200)
    expires_at: str = Field(min_length=1, max_length=40)


class RunLocalChecks(BusinessModel):
    revision_ids: list[Uuid] = Field(min_length=1, max_length=1000)
    rule_ids: list[RuleId] = Field(min_length=1, max_length=200)


class ObservedRange(BusinessModel):
    start_ms: SafeInteger
    end_ms: SafeInteger

    @model_validator(mode="after")
    def positive_range(self) -> Self:
        if self.end_ms <= self.start_ms:
            raise ValueError("Invalid observed range")
        return self


class CheckReport(BusinessModel):
    id: Uuid
    revision_ids: list[Uuid] = Field(min_length=1, max_length=1000)
    rule_ids: list[RuleId] = Field(min_length=1, max_length=200)
    outcome: Literal["pass", "fail", "unknown", "not_applicable"]
    issue_ids: list[Uuid] = Field(max_length=2000)
    method: Literal["local", "ai", "human"]
    observed_ranges: list[ObservedRange] = Field(max_length=1000)
    evidence_media_ids: list[Uuid] = Field(max_length=1000)
    rule_version: str = Field(min_length=1, max_length=100)
    limitations: str = Field(max_length=4000)
