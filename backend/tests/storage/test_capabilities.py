import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.services.projects import ProjectService
from app.storage.errors import ProjectError
from tests.storage.test_projects import command as project_command
from tests.storage.test_projects import grant
from tests.storage.test_settings import command, credential


def profile() -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "providerId": "fixture",
        "modelId": "fixture-text",
        "region": "test",
        "version": "fixture-v1",
        "stage": "story",
        "accountState": "unknown",
        "interfaceState": "verified",
        "qualityState": "unverified",
        "enabled": False,
        "maxReferences": 0,
        "supportedReferenceRoles": [],
        "durationOptionsMs": [],
        "supportsQuery": False,
        "supportsCancel": False,
        "priceSource": "test fixture only",
        "priceDate": "2026-09-16",
        "restrictions": ["fixture only"],
        "phases": ["story_outline"],
        "supportsAudioDrive": False,
        "supportsLipsync": False,
        "voicePresets": [],
        "maxInputBytes": None,
        "maxInputCodePoints": None,
        "resultLifetimeSeconds": None,
        "supportsAnonymousResultDownload": False,
    }


def test_schema_validation_and_default_has_no_free_adapter(tmp_path: Path) -> None:
    invalid = profile()
    invalid["enabled"] = True
    with pytest.raises(ProjectError, match="CAPABILITY_INVALID"):
        ProjectService(tmp_path / "bad", capability_profiles=[invalid])
    service = ProjectService(tmp_path / "good", capability_profiles=[profile()])
    capability = service.get_tool_settings()["capabilities"][0]
    with pytest.raises(ProjectError, match="CONNECTION_CHECK_UNAVAILABLE"):
        service.check_connection(command({"capabilityId": capability["id"]}), 1)
    assert service.get_tool_settings()["revision"] == 0
    service.close()


def test_free_checker_replay_separate_status_and_invalidation(tmp_path: Path) -> None:
    capability = profile()
    calls: list[str] = []

    def check(cap: dict[str, Any], secret: dict[str, Any]) -> bool:
        calls.append(cap["id"])
        assert secret["apiKey"] == "SECRET-SENTINEL-9876"
        return True

    service = ProjectService(
        tmp_path, capability_profiles=[capability], free_checkers={capability["id"]: check}
    )
    service.set_credential("fixture", credential(), 1)
    body = command({"capabilityId": capability["id"]}, 1)
    receipt = service.check_connection(body, 1)
    assert service.check_connection(body, 1) == receipt
    assert calls == [capability["id"]]
    assert service.get_global_job(receipt["resourceId"])["state"] == "succeeded"
    assert service.get_global_operation(body["clientOperationId"])["receipt"] == receipt
    checked = service.get_tool_settings()["capabilities"][0]
    assert checked["accountState"] == "available"
    assert checked["interfaceState"] == "verified"
    assert checked["qualityState"] == "unverified"
    service.delete_credential("fixture", command({"confirmed": True}, 2), 1)
    assert service.get_tool_settings()["capabilities"][0]["accountState"] == "unknown"
    assert service.get_global_job(receipt["resourceId"])["state"] == "succeeded"
    service.close()


def test_failed_checker_does_not_echo_exception(tmp_path: Path) -> None:
    capability = profile()

    def check(cap: dict[str, Any], secret: dict[str, Any]) -> bool:
        raise TimeoutError("SECRET-SENTINEL-9876")

    service = ProjectService(
        tmp_path, capability_profiles=[capability], free_checkers={capability["id"]: check}
    )
    service.set_credential("fixture", credential(), 1)
    receipt = service.check_connection(command({"capabilityId": capability["id"]}, 1), 1)
    job = service.get_global_job(receipt["resourceId"])
    assert job["state"] == "failed"
    assert job["errorCode"] == "CONNECTION_CHECK_FAILED"
    assert "SECRET-SENTINEL" not in json.dumps(job)
    service.close()


def test_stage_configuration_pins_version_and_uses_project_cas(tmp_path: Path) -> None:
    capability = profile()
    service = ProjectService(tmp_path / "app", capability_profiles=[capability])
    directory = tmp_path / "project"
    directory.mkdir()
    service.create_project(project_command(grant(service, directory, "createProject")), 1)
    session = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    args = (session["projectId"], session["projectSessionId"], 1)
    body = command({"phase": "story_outline", "capabilityId": capability["id"]}, 1)
    receipt = service.configure_stage(*args, body)
    assert receipt["committedRevision"] == 2
    assert service.configure_stage(*args, body) == receipt
    assert service.get_tool_settings()["revision"] == 0
    assert service.get_stage_models(*args) == [
        {
            "phase": "story_outline",
            "capabilityId": capability["id"],
            "capabilityVersion": "fixture-v1",
        }
    ]
    with pytest.raises(ProjectError, match="CAPABILITY_PHASE_MISMATCH"):
        service.configure_stage(
            *args, command({"phase": "video", "capabilityId": capability["id"]}, 2)
        )
    service.close()


def test_pending_check_replay_does_not_resubmit_or_revive_replaced_key(tmp_path: Path) -> None:
    capability = profile()
    entered, release = threading.Event(), threading.Event()
    count = 0

    def check(cap: dict[str, Any], secret: dict[str, Any]) -> bool:
        nonlocal count
        count += 1
        entered.set()
        assert release.wait(5)
        return True

    service = ProjectService(
        tmp_path, capability_profiles=[capability], free_checkers={capability["id"]: check}
    )
    service.set_credential("fixture", credential(), 1)
    body = command({"capabilityId": capability["id"]}, 1)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(service.check_connection, body, 1)
        assert entered.wait(5)
        duplicate = service.check_connection(body, 1)
        assert service.get_global_job(duplicate["resourceId"])["state"] == "running"
        service.set_credential("fixture", credential(revision=2), 1)
        release.set()
        assert pending.result(5) == duplicate
    assert count == 1
    assert service.get_tool_settings()["capabilities"][0]["accountState"] == "unknown"
    service.close()


def test_free_check_timeout_and_stage_identity(tmp_path: Path, monkeypatch: Any) -> None:
    from app.storage import capabilities

    capability = profile()
    release = threading.Event()
    monkeypatch.setattr(capabilities, "CHECK_TIMEOUT_SECONDS", 0.02)

    def check(cap: dict[str, Any], secret: dict[str, Any]) -> bool:
        release.wait(5)
        return True

    service = ProjectService(
        tmp_path, capability_profiles=[capability], free_checkers={capability["id"]: check}
    )
    service.set_credential("fixture", credential(), 1)
    receipt = service.check_connection(command({"capabilityId": capability["id"]}, 1), 1)
    release.set()
    assert service.get_global_job(receipt["resourceId"])["errorCode"] == "CONNECTION_CHECK_FAILED"
    with pytest.raises(ProjectError, match="SESSION_EXPIRED"):
        service.get_stage_models(str(uuid4()), str(uuid4()), 2)
    service.close()
