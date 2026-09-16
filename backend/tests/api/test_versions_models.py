from uuid import uuid4

import pytest
from app.api.v1.versions_models import CheckReport, Impact, RunLocalChecks
from app.main import create_app
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.api.test_runtime import make_context


def test_empty_checks_cannot_look_like_a_valid_check_request_or_report() -> None:
    revision = str(uuid4())
    valid = {"revisionIds": [revision], "ruleIds": ["structural"]}
    assert RunLocalChecks.model_validate(valid).revision_ids == [revision]
    for field in ("revisionIds", "ruleIds"):
        with pytest.raises(ValidationError):
            RunLocalChecks.model_validate({**valid, field: []})
    report = {
        "id": str(uuid4()),
        **valid,
        "outcome": "pass",
        "issueIds": [],
        "method": "local",
        "observedRanges": [],
        "evidenceMediaIds": [],
        "ruleVersion": "local-structure-v1",
        "limitations": "Structure only; not a model quality or human review.",
    }
    assert CheckReport.model_validate(report).outcome == "pass"
    for field in ("revisionIds", "ruleIds"):
        with pytest.raises(ValidationError):
            CheckReport.model_validate({**report, field: []})
    with pytest.raises(ValidationError):
        CheckReport.model_validate({**report, "secret": "private"})


def test_impact_keeps_unknown_cost_and_rejects_unsafe_money() -> None:
    payload = {
        "previewId": str(uuid4()),
        "artifactId": str(uuid4()),
        "fromRevisionId": None,
        "toRevisionId": str(uuid4()),
        "affectedArtifactIds": [],
        "affectedScopes": ["export"],
        "estimatedExtraMicroCny": None,
        "requiredChecks": ["structural"],
        "expiresAt": "2026-09-16T06:00:00Z",
    }
    assert Impact.model_validate(payload).estimated_extra_micro_cny is None
    for value in (-1, True, "100", 1.5, 9007199254740992):
        with pytest.raises(ValidationError):
            Impact.model_validate({**payload, "estimatedExtraMicroCny": value})
    with pytest.raises(ValidationError):
        Impact.model_validate({**payload, "affectedScopes": ["arbitrary-private-path"]})


def test_exported_formal_payload_schema_rejects_incomplete_and_cross_kind_content() -> None:
    schema = create_app(make_context()).openapi()
    validator = Draft202012Validator({**schema, "$ref": "#/components/schemas/CompletePayload"})
    assert not validator.is_valid({"kind": "story", "content": {}})
    assert not validator.is_valid({"kind": "story", "content": {"privatePath": "sentinel"}})
    valid = {
        "kind": "subtitle",
        "content": {"audioRevisionId": None, "timingMethod": "manual", "cues": []},
    }
    assert validator.is_valid(valid)
    assert not validator.is_valid({**valid, "kind": "asset"})
