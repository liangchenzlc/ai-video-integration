"""T03 write-only secrets and strictly bounded, safe settings views."""

from typing import Annotated, Literal

from pydantic import Field

from app.api.v1.models import Uuid
from app.api.v1.projects_models import BusinessModel, PositiveInteger, SafeInteger

type ProviderId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$")]
type Persistence = Literal["dpapi", "session_only"]
type PipelinePhase = Literal[
    "story_adaptation",
    "story_outline",
    "story_scene",
    "story_dialogue",
    "image_character",
    "image_location",
    "image_prop",
    "image_keyframe",
    "video",
    "speech",
    "lipsync",
    "music",
    "sfx",
    "check",
]


class ApiKeySecret(BusinessModel):
    kind: Literal["api_key"]
    api_key: str = Field(
        min_length=1, max_length=8192, repr=False, json_schema_extra={"writeOnly": True}
    )


class OssSecret(BusinessModel):
    kind: Literal["oss"]
    access_key_id: str = Field(
        min_length=1, max_length=256, repr=False, json_schema_extra={"writeOnly": True}
    )
    access_key_secret: str = Field(
        min_length=1, max_length=8192, repr=False, json_schema_extra={"writeOnly": True}
    )
    security_token: str | None = Field(
        min_length=1, max_length=16384, repr=False, json_schema_extra={"writeOnly": True}
    )


class SetCredential(BusinessModel):
    secret: Annotated[
        ApiKeySecret | OssSecret,
        Field(discriminator="kind", repr=False, json_schema_extra={"writeOnly": True}),
    ]
    persistence: Persistence


class DeleteCredential(BusinessModel):
    confirmed: bool


class ConfigureStorage(BusinessModel):
    provider_id: ProviderId
    region: str = Field(min_length=1, max_length=100)
    bucket: str = Field(min_length=1, max_length=100)
    credential_ref: Uuid
    retention_hours: Annotated[SafeInteger, Field(ge=1, le=168)]


class ConfigureStage(BusinessModel):
    phase: PipelinePhase
    capability_id: Uuid


class ConnectionCheck(BusinessModel):
    capability_id: Uuid


class StageModel(BusinessModel):
    phase: PipelinePhase
    capability_id: Uuid
    capability_version: str = Field(min_length=1, max_length=100)


class CredentialSummary(BusinessModel):
    id: Uuid
    provider_id: ProviderId
    kind: Literal["api_key", "oss"]
    persistence: Persistence
    masked_suffix: str = Field(min_length=4, max_length=4)


class StorageProfile(ConfigureStorage):
    id: Uuid
    persistence: Persistence


class ToolSummary(BusinessModel):
    version: str = Field(min_length=1, max_length=200)
    h264: bool
    aac: bool
    subtitles: bool


class SettingsDetails(BusinessModel):
    credentials: list[CredentialSummary] = Field(max_length=1000)
    storage_profiles: list[StorageProfile] = Field(max_length=1000)
    tool_summary: ToolSummary | None


class ProviderSummary(BusinessModel):
    provider_id: ProviderId
    credential_configured: bool
    masked_suffix: str | None = Field(min_length=4, max_length=4)
    storage_configured: bool


class Capability(BusinessModel):
    id: Uuid
    provider_id: ProviderId
    model_id: str = Field(min_length=1, max_length=200)
    region: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    stage: Literal["story", "image", "video", "speech", "lipsync", "music", "sfx", "check"]
    phases: list[PipelinePhase] = Field(min_length=1, max_length=14)
    account_state: Literal["unknown", "available", "unavailable"]
    interface_state: Literal["unverified", "verified", "unavailable"]
    quality_state: Literal["unverified", "research_only", "verified"]
    enabled: bool
    max_references: Annotated[SafeInteger, Field(le=16)]
    supported_reference_roles: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        max_length=16
    )
    duration_options_ms: list[PositiveInteger] = Field(max_length=100)
    supports_query: bool
    supports_cancel: bool
    supports_audio_drive: bool
    supports_lipsync: bool
    voice_presets: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        max_length=1000
    )
    max_input_bytes: PositiveInteger | None
    max_input_code_points: PositiveInteger | None
    result_lifetime_seconds: PositiveInteger | None
    supports_anonymous_result_download: bool
    price_source: str = Field(min_length=1, max_length=2000)
    price_date: str = Field(min_length=1, max_length=40)
    restrictions: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(
        max_length=1000
    )


class Settings(BusinessModel):
    revision: SafeInteger
    providers: list[ProviderSummary] = Field(max_length=1000)
    ffmpeg_configured: bool
    capabilities: list[Capability] = Field(max_length=1000)
