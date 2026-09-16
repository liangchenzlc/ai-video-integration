import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.services import generated_media
from app.storage.errors import ProjectError
from tests.storage.test_media import FFMPEG


def test_generated_png_is_decoded_and_replay_keeps_identity(tmp_path: Path) -> None:
    call = str(uuid4())
    first = generated_media.publish_image(
        tmp_path, call, 0, FFMPEG, threading.Event(), synthetic=True
    )
    target = tmp_path / first["relativePath"]
    assert target.is_file()
    assert first["mime"] == "image/png"
    assert (first["width"], first["height"]) == (64, 48)
    assert first["provenance"] == "synthetic"
    second = generated_media.publish_image(
        tmp_path, call, 0, FFMPEG, threading.Event(), synthetic=True
    )
    assert first == second
    assert len(list((tmp_path / "media").iterdir())) == 1


def test_corrupt_png_is_never_published(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(generated_media, "_synthetic_png", lambda: b"broken image")
    with pytest.raises(ProjectError, match="MEDIA_INVALID"):
        generated_media.publish_image(
            tmp_path, str(uuid4()), 0, FFMPEG, threading.Event(), synthetic=True
        )
    assert not list((tmp_path / "media").iterdir())


def test_file_published_before_db_commit_replays_without_download(
    monkeypatch: Any, tmp_path: Path
) -> None:
    call = str(uuid4())
    first = generated_media.publish_image(
        tmp_path, call, 0, FFMPEG, threading.Event(), synthetic=True
    )
    monkeypatch.setattr(
        generated_media, "_synthetic_png", lambda: pytest.fail("must reuse original file")
    )
    second = generated_media.publish_image(
        tmp_path, call, 0, FFMPEG, threading.Event(), synthetic=True
    )
    assert second == first


def test_recovery_detects_altered_published_file(tmp_path: Path) -> None:
    call = str(uuid4())
    first = generated_media.publish_image(
        tmp_path, call, 0, FFMPEG, threading.Event(), synthetic=True
    )
    (tmp_path / first["relativePath"]).write_bytes(b"altered")
    with pytest.raises(ProjectError, match="MEDIA_HASH_MISMATCH"):
        generated_media.publish_image(tmp_path, call, 0, FFMPEG, threading.Event(), synthetic=True)


def test_downloaded_mime_must_match_decoded_image(monkeypatch: Any, tmp_path: Path) -> None:
    def download(url: str, target: Path) -> dict[str, Any]:
        target.write_bytes(generated_media._synthetic_png())
        return {"mime": "image/jpeg"}

    monkeypatch.setattr(generated_media, "download_image", download)
    with pytest.raises(ProjectError, match="RESULT_MEDIA_INVALID"):
        generated_media.publish_image(
            tmp_path, str(uuid4()), 0, FFMPEG, threading.Event(), url="https://signed"
        )
    assert not list((tmp_path / "media").iterdir())


@pytest.mark.parametrize(
    "field,value",
    [
        ("callId", "00000000-0000-4000-8000-000000000001"),
        ("ordinal", 7),
        ("provenance", "generated"),
        ("byteLength", 999999),
    ],
)
def test_corrupted_journal_cannot_change_result_attribution(
    tmp_path: Path, field: str, value: Any
) -> None:
    call = str(uuid4())
    record = generated_media.publish_image(
        tmp_path, call, 0, FFMPEG, threading.Event(), synthetic=True
    )
    journal = tmp_path / ".media-staging" / (record["id"] + ".json")
    record[field] = value
    journal.write_text(json.dumps(record), "utf-8")
    with pytest.raises(ProjectError, match="MEDIA_RECOVERY_REQUIRED"):
        generated_media.publish_image(tmp_path, call, 0, FFMPEG, threading.Event(), synthetic=True)


@pytest.mark.parametrize("mode,code", [("verified", 51), ("renamed", 52)])
def test_process_exit_recovers_exact_verified_image(
    monkeypatch: Any, tmp_path: Path, mode: str, code: int
) -> None:
    call = str(uuid4())
    child = subprocess.run(
        [
            sys.executable,
            "backend/tests/tasks/generated_crash_worker.py",
            str(tmp_path),
            call,
            mode,
        ],
        env=dict(os.environ, PYTHONPATH=str(Path("backend").resolve())),
        capture_output=True,
        timeout=20,
    )
    assert child.returncode == code, child.stderr.decode(errors="replace")
    monkeypatch.setattr(
        generated_media, "_synthetic_png", lambda: pytest.fail("must reuse durable bytes")
    )
    record = generated_media.publish_image(
        tmp_path, call, 0, FFMPEG, threading.Event(), synthetic=True
    )
    assert (tmp_path / record["relativePath"]).is_file()
    assert len(list((tmp_path / "media").iterdir())) == 1
    assert not list((tmp_path / ".media-staging").glob("*.part"))
