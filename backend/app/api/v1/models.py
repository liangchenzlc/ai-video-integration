"""Strict runtime DTOs. JSON integer semantics agree with the desktop codec."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


def json_integer(value: object) -> int:
    if type(value) is int:
        return value
    if type(value) is float and math.isfinite(value) and value.is_integer():
        return int(value)
    raise ValueError("Expected a JSON integer")


type Uuid = Annotated[str, Field(pattern=UUID_PATTERN, json_schema_extra={"format": "uuid"})]
type Generation = Annotated[int, Field(ge=1, le=2147483647), BeforeValidator(json_integer)]
type Version = Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
type ProtocolVersion = Annotated[Literal[1], BeforeValidator(json_integer)]
type SafeMilliseconds = Annotated[
    int, Field(ge=0, le=9007199254740991), BeforeValidator(json_integer)
]
type RecoveryAction = Literal["none", "retry_connection", "restart_backend", "repair_installation"]
type ErrorCode = Literal[
    "AUTH_REQUIRED",
    "AUTH_INVALID",
    "HOST_REJECTED",
    "ORIGIN_REJECTED",
    "REQUEST_INVALID",
    "NOT_FOUND",
    "METHOD_NOT_ALLOWED",
    "BACKEND_NOT_READY",
    "INTERNAL_ERROR",
]
type CapabilityId = Literal[
    "runtime",
    "projects",
    "credentials",
    "story",
    "visualAssets",
    "storyboard",
    "video",
    "audio",
    "timeline",
    "checks",
    "exports",
    "costs",
]
CAPABILITY_IDS: tuple[CapabilityId, ...] = (
    "runtime",
    "projects",
    "credentials",
    "story",
    "visualAssets",
    "storyboard",
    "video",
    "audio",
    "timeline",
    "checks",
    "exports",
    "costs",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
        hide_input_in_errors=True,
    )


class ErrorDetail(StrictModel):
    code: ErrorCode
    message: str = Field(min_length=1, max_length=256)
    affected_ids: list[Uuid] = Field(alias="affectedIds", max_length=100)
    recoverable_action: RecoveryAction = Field(alias="recoverableAction")


class ErrorResponse(StrictModel):
    request_id: Uuid = Field(alias="requestId")
    error: ErrorDetail


class HealthData(StrictModel):
    status: Literal["ready"]
    runtime_id: Uuid = Field(alias="runtimeId")
    generation: Generation
    api_version: ProtocolVersion = Field(alias="apiVersion")
    control_version: ProtocolVersion = Field(alias="controlVersion")
    backend_version: Version = Field(alias="backendVersion")
    uptime_ms: SafeMilliseconds = Field(alias="uptimeMs")


class HealthResponse(StrictModel):
    request_id: Uuid = Field(alias="requestId")
    data: HealthData


class Capability(StrictModel):
    id: CapabilityId
    enabled: bool
    reason_code: Literal["AVAILABLE", "NOT_IMPLEMENTED"] = Field(alias="reasonCode")

    @model_validator(mode="after")
    def match_implementation(self) -> Capability:
        available = self.id == "runtime"
        if self.enabled != available or self.reason_code != (
            "AVAILABLE" if available else "NOT_IMPLEMENTED"
        ):
            raise ValueError("Capability does not match implemented runtime")
        return self


class CapabilitiesData(StrictModel):
    runtime_id: Uuid = Field(alias="runtimeId")
    generation: Generation
    capabilities: list[Capability] = Field(
        min_length=12, max_length=12, json_schema_extra={"uniqueItems": True}
    )

    @model_validator(mode="after")
    def ordered_capabilities(self) -> CapabilitiesData:
        if tuple(item.id for item in self.capabilities) != CAPABILITY_IDS:
            raise ValueError("Capability order or identity mismatch")
        return self


class CapabilitiesResponse(StrictModel):
    request_id: Uuid = Field(alias="requestId")
    data: CapabilitiesData
