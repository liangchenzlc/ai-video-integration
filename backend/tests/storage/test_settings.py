import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.services.projects import ProjectService
from app.storage.database import connect
from app.storage.errors import ProjectError


def command(payload: dict[str, Any], revision: int = 0) -> dict[str, Any]:
    return {"clientOperationId": str(uuid4()), "expectedRevision": revision, "payload": payload}


def credential(persistence: str = "session_only", revision: int = 0) -> dict[str, Any]:
    return command(
        {
            "secret": {"kind": "api_key", "apiKey": "SECRET-SENTINEL-9876"},
            "persistence": persistence,
        },
        revision,
    )


def test_session_secret_replay_cas_and_restart(tmp_path: Path) -> None:
    service = ProjectService(tmp_path)
    body = credential()
    receipt = service.set_credential("example", body, 1)
    assert service.set_credential("example", body, 1) == receipt
    assert service.get_tool_settings()["revision"] == 1
    assert service.get_settings_details()["credentials"][0]["maskedSuffix"] == "9876"
    changed = json.loads(json.dumps(body))
    changed["payload"]["secret"]["apiKey"] = "changed-secret"
    with pytest.raises(ProjectError, match="OPERATION_ID_REUSED"):
        service.set_credential("example", changed, 1)
    with pytest.raises(ProjectError, match="REVISION_CONFLICT"):
        service.set_credential("other", credential(), 1)
    service.close()
    assert b"SECRET-SENTINEL" not in (tmp_path / "application.sqlite3").read_bytes()
    reopened = ProjectService(tmp_path)
    assert reopened.get_settings_details()["credentials"] == []
    assert reopened.get_tool_settings()["revision"] == 1
    reopened.close()


def test_dpapi_roundtrip_failure_and_no_plaintext(tmp_path: Path, monkeypatch: Any) -> None:
    from app.storage.credentials import protect, unprotect

    secret = b"DPAPI-SENTINEL-secret"
    ciphertext = protect(secret)
    assert secret not in ciphertext
    assert unprotect(ciphertext) == secret
    with pytest.raises(ProjectError, match="CREDENTIAL_UNAVAILABLE"):
        unprotect(b"corrupt-other-user-ciphertext")
    service = ProjectService(tmp_path)
    body = credential("dpapi")
    service.set_credential("example", body, 1)
    service.close()
    service = ProjectService(tmp_path)
    assert service.get_settings_details()["credentials"][0]["persistence"] == "dpapi"
    from app.storage import credentials

    def fail(value: bytes) -> bytes:
        raise ProjectError("CREDENTIAL_ENCRYPTION_FAILED", 503)

    monkeypatch.setattr(credentials, "protect", fail)
    with pytest.raises(ProjectError, match="CREDENTIAL_ENCRYPTION_FAILED"):
        service.set_credential("other", credential("dpapi", 1), 1)
    assert service.get_tool_settings()["revision"] == 1
    with connect(tmp_path / "application.sqlite3", "ro") as db:
        operations = [tuple(row) for row in db.execute("SELECT * FROM global_operations")]
        assert "SECRET-SENTINEL" not in str(operations)
        assert "apiKey" not in str(operations)
        assert "accessKeySecret" not in str(operations)
        assert db.execute("SELECT count(*) FROM credentials").fetchone()[0] == 1
    service.close()
    assert b"SECRET-SENTINEL" not in (tmp_path / "application.sqlite3").read_bytes()


@pytest.mark.parametrize("persistence", ["session_only", "dpapi"])
def test_oss_profile_lifetime_and_delete(tmp_path: Path, persistence: str) -> None:
    service = ProjectService(tmp_path)
    receipt = service.set_credential(
        "oss",
        command(
            {
                "persistence": persistence,
                "secret": {
                    "kind": "oss",
                    "accessKeyId": "id-1234",
                    "accessKeySecret": "OSS-SECRET-8765",
                    "securityToken": None,
                },
            }
        ),
        1,
    )
    profile = command(
        {
            "providerId": "oss",
            "region": "cn-test",
            "bucket": "my-bucket",
            "credentialRef": receipt["resourceId"],
            "retentionHours": 48,
        },
        1,
    )
    saved = service.configure_storage(profile, 1)
    assert service.configure_storage(profile, 1) == saved
    assert service.get_settings_details()["storageProfiles"][0]["persistence"] == persistence
    with connect(tmp_path / "application.sqlite3", "ro") as db:
        assert db.execute("SELECT count(*) FROM storage_profiles").fetchone()[0] == (
            1 if persistence == "dpapi" else 0
        )
    deleted = command({"confirmed": True}, 2)
    service.delete_credential("oss", deleted, 1)
    assert service.get_settings_details()["storageProfiles"] == []
    assert service.get_settings_details()["credentials"] == []
    service.close()


@pytest.mark.parametrize("secret", ["Q", "Q2", "Q2Z", "Q2Z9"])
def test_short_keys_are_fully_masked(tmp_path: Path, secret: str) -> None:
    service = ProjectService(tmp_path)
    body = credential()
    body["payload"]["secret"]["apiKey"] = secret
    service.set_credential("fixture", body, 1)
    assert service.get_settings_details()["credentials"][0]["maskedSuffix"] == "****"
    assert service.get_tool_settings()["providers"][0]["maskedSuffix"] == "****"
    service.close()


def test_tool_details_and_credential_kind_are_safe(tmp_path: Path) -> None:
    service = ProjectService(tmp_path)
    with connect(tmp_path / "application.sqlite3") as db, db:
        db.execute(
            "UPDATE settings SET ffmpeg_path=?,ffmpeg_probe_json=?",
            (
                "C:/private/tools/ffmpeg.exe",
                json.dumps(
                    {"version": "8", "build": "private", "h264": True, "aac": True, "libass": True}
                ),
            ),
        )
    assert service.get_settings_details()["toolSummary"] == {
        "version": "8",
        "h264": True,
        "aac": True,
        "subtitles": True,
    }
    assert "private" not in json.dumps(service.get_settings_details())
    receipt = service.set_credential("fixture", credential(), 1)
    with pytest.raises(ProjectError, match="CREDENTIAL_UNAVAILABLE"):
        service.configure_storage(
            command(
                {
                    "providerId": "fixture",
                    "region": "cn-test",
                    "bucket": "bucket",
                    "credentialRef": receipt["resourceId"],
                    "retentionHours": 48,
                },
                1,
            ),
            1,
        )
    with pytest.raises(ProjectError, match="VALIDATION_FAILED"):
        service.delete_credential("fixture", command({"confirmed": False}, 1), 1)
    assert service.get_tool_settings()["revision"] == 1
    service.close()
