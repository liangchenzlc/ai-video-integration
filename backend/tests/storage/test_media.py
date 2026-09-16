import errno
import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.services.projects import ProjectService
from app.storage.database import connect
from tests.storage.test_projects import command, grant

FFMPEG = Path(__file__).resolve().parents[3] / (
    ".local/research-20260915/ffmpeg/ffmpeg-9.0.1-essentials_build/bin/ffmpeg.exe"
)


def mutation(revision: int, **payload: Any) -> dict[str, Any]:
    return {"clientOperationId": str(uuid4()), "expectedRevision": revision, "payload": payload}


@pytest.fixture
def media_project(tmp_path: Path) -> Any:
    service = ProjectService(tmp_path / "app")
    directory = tmp_path / "project"
    directory.mkdir()
    service.create_project(command(grant(service, directory, "createProject")), 1)
    session = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    args = (session["projectId"], session["projectSessionId"], 1)
    yield service, directory, args
    service.close()


def configure(service: Any) -> dict[str, Any]:
    return service.configure_tools(
        mutation(
            service.get_tool_settings()["revision"], ffmpegGrantId=grant(service, FFMPEG, "ffmpeg")
        ),
        1,
    )


def fixture_media(path: Path) -> Path:
    subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x48",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    return path


def wait_job(service: Any, args: Any, receipt: Any) -> Any:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        job = service.get_job(*args, receipt["resourceId"])
        if job["state"] in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_tools_require_grant_and_persist_redacted(media_project: Any) -> None:
    service, _, _ = media_project
    assert service.get_tool_settings()["ffmpegConfigured"] is False
    request = mutation(0, ffmpegGrantId=grant(service, FFMPEG, "ffmpeg"))
    first = service.configure_tools(request, 1)
    assert service.configure_tools(request, 1) == first
    assert service.get_global_operation(request["clientOperationId"])["receipt"] == first
    assert service.get_tool_settings()["ffmpegConfigured"] is True
    assert str(FFMPEG) not in json.dumps(service.get_tool_settings())
    with pytest.raises(Exception, match="REVISION_CONFLICT"):
        service.configure_tools(mutation(0, ffmpegGrantId=str(uuid4())), 1)


def test_real_import_replay_move_missing_relocate(media_project: Any, tmp_path: Path) -> None:
    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "source.png")
    request = mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    receipt = service.import_media(*args, request)
    assert receipt["state"] == "accepted"
    assert service.import_media(*args, request) == receipt
    job = wait_job(service, args, receipt)
    assert job["state"] == "succeeded", job
    media = service.get_media(*args, job["resultId"])
    assert (media["width"], media["height"], media["mime"]) == (64, 48, "image/png")
    assert media["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert str(source) not in json.dumps([media, job, service.list_media(*args)])
    service.close_session(args[1], 1)
    moved = tmp_path / "moved"
    shutil.move(directory, moved)
    session = service.open_project(
        {"directoryGrantId": grant(service, moved, "openProject"), "requestedMode": "write"}, 1
    )
    args = (session["projectId"], session["projectSessionId"], 1)
    target = service.media_file(*args, media["id"])
    assert target.read_bytes() == source.read_bytes()
    target.unlink()
    assert service.get_media(*args, media["id"])["availability"] == "missing"
    relocate = service.relocate_media(
        *args,
        media["id"],
        mutation(
            service.get_project(*args)["revision"],
            fileGrantId=grant(service, source, "importMedia"),
            expectedHash=media["sha256"],
        ),
    )
    assert wait_job(service, args, relocate)["resultId"] == media["id"]
    assert service.media_file(*args, media["id"]).read_bytes() == source.read_bytes()


def test_invalid_import_and_readonly(media_project: Any, tmp_path: Path) -> None:
    service, directory, args = media_project
    source = tmp_path / "bad.png"
    source.write_bytes(b"not an image")
    with pytest.raises(Exception, match="MEDIA_TOOLS_NOT_CONFIGURED"):
        service.import_media(
            *args,
            mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference"),
        )
    configure(service)
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    assert wait_job(service, args, receipt)["state"] == "failed"
    assert source.read_bytes() == b"not an image"
    second = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject", 2), "requestedMode": "write"},
        2,
    )
    with pytest.raises(Exception, match="PROJECT_READ_ONLY"):
        service.import_media(
            args[0],
            second["projectSessionId"],
            2,
            mutation(2, fileGrantId=str(uuid4()), purpose="reference"),
        )


def test_backup_includes_live_wal_and_is_unique(media_project: Any) -> None:
    service, directory, args = media_project
    with connect(directory / "project.sqlite3") as db:
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("UPDATE projects SET name='WAL latest'")
        db.commit()
        backup = service.backup_project(*args)
        other = service.backup_project(*args)
        assert backup != other
        with connect(backup, "ro") as copied:
            assert copied.execute("SELECT name FROM projects").fetchone()[0] == "WAL latest"
            assert copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert (directory / "project.sqlite3").exists()


def test_cancel_during_copy_retains_lock_and_allows_draft_save(
    media_project: Any, tmp_path: Path
) -> None:
    from app.storage.locking import ProjectLock

    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "cancel.png")
    entered, release = threading.Event(), threading.Event()

    def pause(boundary: str) -> None:
        if boundary == "copy_chunk":
            entered.set()
            assert release.wait(10)

    service._media.fault_hook = pause
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    try:
        assert entered.wait(10)
        draft_id = str(uuid4())
        start = time.monotonic()
        service.save_draft(
            *args,
            draft_id,
            mutation(
                2,
                draftId=draft_id,
                artifactId=str(uuid4()),
                baseRevisionId=None,
                content={"kind": "story", "content": {}},
            ),
        )
        assert time.monotonic() - start < 1
        request = mutation(3, reason="user cancelled")
        cancelled = service.cancel_job(*args, receipt["resourceId"], request)
        assert service.cancel_job(*args, receipt["resourceId"], request) == cancelled
        assert service.get_job(*args, receipt["resourceId"])["state"] == "cancelled"
        service.close_session(args[1], 1)
        assert ProjectLock.acquire(directory) is None
    finally:
        release.set()
        service.close()
    lock = ProjectLock.acquire(directory)
    assert lock is not None
    lock.close()
    assert source.exists()
    assert list((directory / ".media-staging").iterdir())


@pytest.mark.parametrize("boundary", ["verified", "renamed", "copy_chunk"])
def test_recovery_never_registers_partial_files(
    media_project: Any, tmp_path: Path, boundary: str
) -> None:
    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "recover.png")

    def fail(point: str) -> None:
        if point == boundary:
            raise RuntimeError("simulated process boundary")

    service._media.fault_hook = fail
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    deadline = time.monotonic() + 10
    while service._media.busy(directory) and time.monotonic() < deadline:
        time.sleep(0.02)
    service.close()
    restarted = ProjectService(service.app_data_dir)
    try:
        opened = restarted.open_project(
            {
                "directoryGrantId": grant(restarted, directory, "openProject"),
                "requestedMode": "write",
            },
            1,
        )
        args = (opened["projectId"], opened["projectSessionId"], 1)
        job = wait_job(restarted, args, receipt)
        if boundary == "copy_chunk":
            assert job["state"] == "failed"
            assert job["errorCode"] == "MEDIA_RECOVERY_REQUIRED"
            assert list((directory / ".media-staging").iterdir())
        else:
            assert job["state"] == "succeeded", job
            assert restarted.media_file(*args, job["resultId"]).read_bytes() == source.read_bytes()
        assert source.exists()
    finally:
        restarted.close()


def test_relocate_wrong_content_preserves_identity(media_project: Any, tmp_path: Path) -> None:
    service, _, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "original.png")
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    job = wait_job(service, args, receipt)
    original = service.get_media(*args, job["resultId"])
    service.media_file(*args, original["id"]).unlink()
    wrong = tmp_path / "wrong.png"
    wrong.write_bytes(source.read_bytes() + b"changed")
    relocated = service.relocate_media(
        *args,
        original["id"],
        mutation(
            2, fileGrantId=grant(service, wrong, "importMedia"), expectedHash=original["sha256"]
        ),
    )
    failed = wait_job(service, args, relocated)
    assert (failed["state"], failed["errorCode"]) == ("failed", "MEDIA_HASH_MISMATCH")
    assert service.get_media(*args, original["id"])["sha256"] == original["sha256"]
    assert service.get_media(*args, original["id"])["availability"] == "missing"
    assert wrong.exists()


def test_limits_and_space_reject_before_acceptance(
    media_project: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    from app.storage import tools

    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "limits.png")
    monkeypatch.setattr(tools, "MAX_BYTES", 10)
    with pytest.raises(Exception, match="MEDIA_SIZE_LIMIT"):
        service.import_media(
            *args,
            mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference"),
        )
    monkeypatch.setattr(tools, "MAX_BYTES", 2 * 1024**3)
    usage = shutil.disk_usage(directory)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: type(usage)(usage.total, usage.used, 1))
    with pytest.raises(Exception, match="INSUFFICIENT_DISK_SPACE"):
        service.import_media(
            *args,
            mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference"),
        )
    assert service.get_project(*args)["revision"] == 1


def test_cross_method_operation_reuse_rejected(media_project: Any, tmp_path: Path) -> None:
    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "replay.png")
    request = mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    receipt = service.import_media(*args, request)
    wait_job(service, args, receipt)
    with connect(directory / "project.sqlite3") as db, db:
        db.execute(
            "UPDATE operations SET operation_name='saveDraft' WHERE id=?",
            (request["clientOperationId"],),
        )
    with pytest.raises(Exception, match="OPERATION_ID_REUSED"):
        service.import_media(*args, request)


@pytest.mark.parametrize(
    "extension,mime",
    [
        (".jpg", "image/jpeg"),
        (".mp4", "video/mp4"),
        (".wav", "audio/wav"),
        (".mp3", "audio/mpeg"),
        (".m4a", "audio/mp4"),
    ],
)
def test_real_supported_formats(
    media_project: Any, tmp_path: Path, extension: str, mime: str
) -> None:
    service, _, args = media_project
    configure(service)
    source = tmp_path / ("sample" + extension)
    fixture = "color=c=blue:s=64x48" if extension in {".jpg", ".mp4"} else "sine=frequency=440"
    subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            fixture,
            "-t",
            "0.2",
            *(["-frames:v", "1"] if extension == ".jpg" else []),
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    job = wait_job(service, args, receipt)
    assert job["state"] == "succeeded", job
    assert service.get_media(*args, job["resultId"])["mime"] == mime


def test_actual_process_exit_after_rename_recovers(media_project: Any, tmp_path: Path) -> None:
    service, directory, _ = media_project
    configure(service)
    source = fixture_media(tmp_path / "crash.png")
    service.close()
    request_path = tmp_path / "request.json"
    script = """
import json, os, sys, time
from pathlib import Path
from uuid import uuid4
from app.services.projects import ProjectService
from tests.storage.test_projects import grant
service = ProjectService(Path(sys.argv[1]))
session = service.open_project({'directoryGrantId':grant(service,Path(sys.argv[2]),'openProject'),
                               'requestedMode':'write'},1)
request = {'clientOperationId':str(uuid4()), 'expectedRevision':1,
           'payload':{'fileGrantId':grant(service,Path(sys.argv[3]),'importMedia'),
                      'purpose':'reference'}}
Path(sys.argv[4]).write_text(json.dumps(request))
def fault(boundary):
    if boundary == 'renamed': os._exit(77)
service._media.fault_hook = fault
service.import_media(session['projectId'],session['projectSessionId'],1,request)
time.sleep(25)
os._exit(78)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(service.app_data_dir),
            str(directory),
            str(source),
            str(request_path),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 77, result.stderr
    restarted = ProjectService(service.app_data_dir)
    try:
        opened = restarted.open_project(
            {
                "directoryGrantId": grant(restarted, directory, "openProject"),
                "requestedMode": "write",
            },
            1,
        )
        args = (opened["projectId"], opened["projectSessionId"], 1)
        request = json.loads(request_path.read_text())
        receipt = restarted.get_project_operation(*args, request["clientOperationId"])["receipt"]
        job = wait_job(restarted, args, receipt)
        assert job["state"] == "succeeded", job
        assert restarted.import_media(*args, request) == receipt
        assert restarted.media_file(*args, job["resultId"]).read_bytes() == source.read_bytes()
    finally:
        restarted.close()


def test_queued_job_survives_restart(media_project: Any, tmp_path: Path, monkeypatch: Any) -> None:
    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "queued.png")
    monkeypatch.setattr(service._media, "enqueue", lambda *_: None)
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    assert service.get_job(*args, receipt["resourceId"])["state"] == "queued"
    service.close()
    restarted = ProjectService(service.app_data_dir)
    try:
        opened = restarted.open_project(
            {
                "directoryGrantId": grant(restarted, directory, "openProject"),
                "requestedMode": "write",
            },
            1,
        )
        args = (opened["projectId"], opened["projectSessionId"], 1)
        assert wait_job(restarted, args, receipt)["state"] == "succeeded"
    finally:
        restarted.close()


def test_modified_verified_file_is_preserved_and_quarantined(
    media_project: Any, tmp_path: Path
) -> None:
    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "verified.png")

    def fault(boundary: str) -> None:
        if boundary == "verified":
            raise RuntimeError("interrupt")

    service._media.fault_hook = fault
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    deadline = time.monotonic() + 10
    while service._media.busy(directory) and time.monotonic() < deadline:
        time.sleep(0.02)
    service.close()
    staged = next((directory / ".media-staging").iterdir())
    staged.write_bytes(b"unknown original must survive")
    restarted = ProjectService(service.app_data_dir)
    try:
        opened = restarted.open_project(
            {
                "directoryGrantId": grant(restarted, directory, "openProject"),
                "requestedMode": "write",
            },
            1,
        )
        args = (opened["projectId"], opened["projectSessionId"], 1)
        job = wait_job(restarted, args, receipt)
        assert (job["state"], job["errorCode"]) == ("failed", "MEDIA_HASH_MISMATCH")
        assert staged.read_bytes() == b"unknown original must survive"
        assert restarted.list_media(*args)["items"] == []
    finally:
        restarted.close()


def test_pixel_limit_and_entire_missing_directory(
    media_project: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    from app.storage import tools

    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "pixels.png")
    monkeypatch.setattr(tools, "MAX_PIXELS", 100)
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    assert wait_job(service, args, receipt)["errorCode"] == "MEDIA_PIXEL_LIMIT"
    monkeypatch.setattr(tools, "MAX_PIXELS", 40_000_000)
    receipt = service.import_media(
        *args, mutation(2, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    job = wait_job(service, args, receipt)
    (directory / "media").rename(directory / "lost-media")
    assert service.get_media(*args, job["resultId"])["availability"] == "missing"
    with pytest.raises(Exception, match="MEDIA_MISSING"):
        service.media_file(*args, job["resultId"])


def test_jobs_discoverable_after_reopen(media_project: Any, tmp_path: Path) -> None:
    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "discover.png")
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    wait_job(service, args, receipt)
    service.close_session(args[1], 1)
    opened = service.open_project(
        {"directoryGrantId": grant(service, directory, "openProject"), "requestedMode": "write"}, 1
    )
    args = (opened["projectId"], opened["projectSessionId"], 1)
    jobs = service.list_jobs(*args)
    assert jobs[0]["id"] == receipt["resourceId"]
    assert str(source) not in json.dumps(jobs)
    with pytest.raises(Exception, match="SESSION_EXPIRED"):
        service.list_jobs(args[0], args[1], 2)


def test_disk_full_during_copy_is_distinct_and_preserves_partial(
    media_project: Any, tmp_path: Path
) -> None:
    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "full.png")

    def fault(boundary: str) -> None:
        if boundary == "copy_chunk":
            raise OSError(errno.ENOSPC, "disk full")

    service._media.fault_hook = fault
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    assert wait_job(service, args, receipt)["errorCode"] == "INSUFFICIENT_DISK_SPACE"
    assert source.exists()
    assert list((directory / ".media-staging").iterdir())


def test_corrupt_video_tail_never_becomes_available(media_project: Any, tmp_path: Path) -> None:
    service, _, args = media_project
    configure(service)
    source = tmp_path / "bad-tail.mp4"
    subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x48:rate=10",
            "-t",
            "12",
            "-c:v",
            "libx264",
            "-g",
            "10",
            "-movflags",
            "+faststart",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    contents = source.read_bytes()
    source.write_bytes(contents[:-400] + b"\x00" * 400)
    # Header/first seconds still parse: corruption exists beyond the former sample check.
    probed = subprocess.run(
        [
            str(FFMPEG.with_name("ffprobe.exe")),
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(source),
        ],
        capture_output=True,
        timeout=20,
    )
    assert probed.returncode == 0
    assert json.loads(probed.stdout)["streams"][0]["width"] == 64
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="video")
    )
    job = wait_job(service, args, receipt)
    assert job["state"] == "failed", job
    assert job["errorCode"] == "MEDIA_INVALID"
    assert service.list_media(*args)["items"] == []


def test_cancellation_interrupts_running_decoder(
    media_project: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    from app.storage import tools

    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "decoding.png")
    entered = threading.Event()

    def slow_decode(
        ffmpeg: Path, path: Path, stop: threading.Event, cancelled: threading.Event | None = None
    ) -> Any:
        entered.set()
        tools.run(
            [sys.executable, "-c", "import time;time.sleep(60)"],
            stop,
            timeout=120,
            cancelled=cancelled,
        )
        raise AssertionError("decoder was not interrupted")

    monkeypatch.setattr(tools, "probe_media", slow_decode)
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    assert entered.wait(10)
    service.cancel_job(*args, receipt["resourceId"], mutation(2, reason="cancel decoding"))
    deadline = time.monotonic() + 3
    while service._media.busy(directory) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not service._media.busy(directory)
    assert service.get_job(*args, receipt["resourceId"])["state"] == "cancelled"
    assert source.exists()


def test_tool_inspection_does_not_hold_draft_mutex(media_project: Any, monkeypatch: Any) -> None:
    from app.storage import tools

    service, _, args = media_project
    entered, release = threading.Event(), threading.Event()
    original = tools.inspect_tools

    def slow_inspect(path: Path) -> dict[str, Any]:
        entered.set()
        assert release.wait(10)
        return original(path)

    monkeypatch.setattr(tools, "inspect_tools", slow_inspect)
    request = mutation(0, ffmpegGrantId=grant(service, FFMPEG, "ffmpeg"))
    results: list[Any] = []

    def configure_in_thread() -> None:
        try:
            results.append(service.configure_tools(request, 1))
        except Exception as error:
            results.append(error)

    thread = threading.Thread(target=configure_in_thread)
    thread.start()
    try:
        assert entered.wait(10)
        draft_id = str(uuid4())
        start = time.monotonic()
        service.save_draft(
            *args,
            draft_id,
            mutation(
                1,
                draftId=draft_id,
                artifactId=str(uuid4()),
                baseRevisionId=None,
                content={"kind": "story", "content": {"sourceText": "saved during tool check"}},
            ),
        )
        assert time.monotonic() - start < 1
    finally:
        release.set()
        thread.join(timeout=10)
    assert results and isinstance(results[0], dict), results


def test_shutdown_is_bounded_and_retains_busy_lock(media_project: Any, tmp_path: Path) -> None:
    from app.storage.locking import ProjectLock

    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "shutdown.png")
    entered, release = threading.Event(), threading.Event()

    def blocked_io(boundary: str) -> None:
        if boundary == "copy_chunk":
            entered.set()
            assert release.wait(10)

    service._media.fault_hook = blocked_io
    service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    assert entered.wait(10)
    try:
        start = time.monotonic()
        service.close()
        assert time.monotonic() - start < 3
        assert ProjectLock.acquire(directory) is None
    finally:
        release.set()
        service._media.thread.join(timeout=5)
    lock = ProjectLock.acquire(directory)
    assert lock is not None
    lock.close()
    assert source.exists()


def test_media_pagination_has_stable_cursor_and_no_silent_loss(
    media_project: Any, tmp_path: Path
) -> None:
    service, _, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "pages.png")
    ids = []
    for revision in (1, 2, 3):
        receipt = service.import_media(
            *args,
            mutation(
                revision, fileGrantId=grant(service, source, "importMedia"), purpose="reference"
            ),
        )
        ids.append(wait_job(service, args, receipt)["resultId"])
    first = service.list_media(*args, limit=2)
    second = service.list_media(*args, limit=2, cursor=first["nextCursor"])
    assert [item["id"] for item in first["items"] + second["items"]] == sorted(ids)
    assert second["nextCursor"] is None
    with pytest.raises(Exception, match="VALIDATION_FAILED"):
        service.list_media(*args, limit=201)


def test_replaced_project_identity_rejects_reads_replays_and_backup(
    media_project: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "identity.png")
    request = mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    receipt = service.import_media(*args, request)
    job = wait_job(service, args, receipt)
    monkeypatch.setattr(service._media, "enqueue", lambda *_: None)
    pending = service.import_media(
        *args, mutation(2, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    cancellation = mutation(3, reason="cancel before identity replacement")
    service.cancel_job(*args, pending["resourceId"], cancellation)
    with connect(directory / "project.sqlite3") as db, db:
        db.execute("UPDATE projects SET id=?", (str(uuid4()),))
    calls = [
        lambda: service.get_media(*args, job["resultId"]),
        lambda: service.list_media(*args),
        lambda: service.media_file(*args, job["resultId"]),
        lambda: service.get_job(*args, job["id"]),
        lambda: service.list_jobs(*args),
        lambda: service.import_media(*args, request),
        lambda: service.cancel_job(*args, pending["resourceId"], cancellation),
        lambda: service.backup_project(*args),
    ]
    for call in calls:
        with pytest.raises(Exception, match="OBJECT_NOT_FOUND"):
            call()


@pytest.mark.parametrize("failure_stage", ["recovery", "before_session"])
def test_failed_reopen_does_not_release_executors_lock(
    media_project: Any, tmp_path: Path, monkeypatch: Any, failure_stage: str
) -> None:
    from app.storage.errors import ProjectError
    from app.storage.locking import ProjectLock

    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "reopen.png")
    entered, release = threading.Event(), threading.Event()

    def pause(boundary: str) -> None:
        if boundary == "copy_chunk":
            entered.set()
            assert release.wait(10)

    service._media.fault_hook = pause
    service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    assert entered.wait(10)
    service.close_session(args[1], 1)

    def fail_recovery(*_: Any) -> None:
        raise ProjectError("STORAGE_UNAVAILABLE", 503)

    if failure_stage == "recovery":
        monkeypatch.setattr(service._media, "recover", fail_recovery)
    else:
        monkeypatch.setattr(service, "_recent", fail_recovery)
    try:
        with pytest.raises(Exception, match="STORAGE_UNAVAILABLE"):
            service.open_project(
                {
                    "directoryGrantId": grant(service, directory, "openProject"),
                    "requestedMode": "write",
                },
                1,
            )
        assert service._media.busy(directory)
        acquired = ProjectLock.acquire(directory)
        if acquired:
            acquired.close()
        assert acquired is None
        assert not service._sessions
    finally:
        release.set()
        service.close()


def test_worker_never_mutates_replacement_project(media_project: Any, tmp_path: Path) -> None:
    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "worker-identity.png")
    entered, release = threading.Event(), threading.Event()

    def pause(boundary: str) -> None:
        if boundary == "copy_chunk":
            entered.set()
            assert release.wait(10)

    service._media.fault_hook = pause
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    assert entered.wait(10)
    with connect(directory / "project.sqlite3") as db, db:
        db.execute("UPDATE projects SET id=?", (str(uuid4()),))
    release.set()
    deadline = time.monotonic() + 10
    while service._media.busy(directory) and time.monotonic() < deadline:
        time.sleep(0.02)
    with connect(directory / "project.sqlite3", "ro") as db:
        row = db.execute(
            "SELECT state,error_code FROM local_jobs WHERE id=?", (receipt["resourceId"],)
        ).fetchone()
        assert (row["state"], row["error_code"]) == ("running", None)
        assert db.execute("SELECT count(*) FROM media_files").fetchone()[0] == 0


@pytest.mark.parametrize("fail", [False, True])
def test_inflight_tool_retries_share_original_result(
    media_project: Any, monkeypatch: Any, fail: bool
) -> None:
    from app.storage import tools
    from app.storage.errors import ProjectError

    service, _, _ = media_project
    entered, release, retry_done = threading.Event(), threading.Event(), threading.Event()
    original = tools.inspect_tools
    probes: list[Path] = []

    def deferred(path: Path) -> dict[str, Any]:
        probes.append(path)
        entered.set()
        assert release.wait(10)
        if fail:
            raise ProjectError("MEDIA_TOOLS_CAPABILITY_MISSING", 422)
        return original(path)

    monkeypatch.setattr(tools, "inspect_tools", deferred)
    request = mutation(0, ffmpegGrantId=grant(service, FFMPEG, "ffmpeg"))
    results: list[Any] = []

    def invoke(retrying: bool = False) -> None:
        try:
            results.append(service.configure_tools(request, 1))
        except Exception as error:
            results.append(error)
        finally:
            if retrying:
                retry_done.set()

    first = threading.Thread(target=invoke)
    second = threading.Thread(target=invoke, args=(True,))
    first.start()
    try:
        assert entered.wait(10)
        with pytest.raises(Exception, match="OBJECT_NOT_FOUND"):
            service.get_global_operation(request["clientOperationId"])
        second.start()
        assert not retry_done.wait(0.1), results
        changed = {**request, "payload": {"ffmpegGrantId": str(uuid4())}}
        with pytest.raises(Exception, match="OPERATION_ID_REUSED"):
            service.configure_tools(changed, 1)
    finally:
        release.set()
        first.join(timeout=10)
        if second.ident:
            second.join(timeout=10)
    assert len(probes) == 1
    assert len(results) == 2
    if fail:
        assert [str(result) for result in results] == ["MEDIA_TOOLS_CAPABILITY_MISSING"] * 2
    else:
        assert isinstance(results[0], dict)
        assert results[0] == results[1]
        assert service.configure_tools(request, 1) == results[0]


def test_queued_worker_rejects_replacement_identity(
    media_project: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    service, directory, args = media_project
    configure(service)
    source = fixture_media(tmp_path / "queued-identity.png")
    enqueue = service._media.enqueue
    monkeypatch.setattr(service._media, "enqueue", lambda *_: None)
    receipt = service.import_media(
        *args, mutation(1, fileGrantId=grant(service, source, "importMedia"), purpose="reference")
    )
    with connect(directory / "project.sqlite3") as db, db:
        db.execute("UPDATE projects SET id=?", (str(uuid4()),))
    enqueue(directory, receipt["resourceId"], args[0])
    deadline = time.monotonic() + 10
    while service._media.busy(directory) and time.monotonic() < deadline:
        time.sleep(0.02)
    with connect(directory / "project.sqlite3", "ro") as db:
        row = db.execute(
            "SELECT state,error_code FROM local_jobs WHERE id=?", (receipt["resourceId"],)
        ).fetchone()
        assert (row["state"], row["error_code"]) == ("queued", None)
        assert db.execute("SELECT count(*) FROM media_files").fetchone()[0] == 0
    assert not (directory / ".media-staging").exists()
