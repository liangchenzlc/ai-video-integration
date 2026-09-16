"""Verified image publication with a durable file journal for candidate replay."""

import hashlib
import json
import os
import sqlite3
import struct
import threading
import zlib
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.result_download import download_image
from app.storage import tools
from app.storage.errors import ProjectError
from app.storage.media import require_space
from app.storage.paths import checked_path, relative_file
from app.storage.settings import canonical
from app.storage.task_plans import identifier


def _synthetic_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
        )

    pixels = b"".join(b"\0" + bytes((64, 128, 180)) * 64 for _ in range(48))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 64, 48, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _publish(staging: Path, target: Path) -> None:
    if os.name == "nt":
        staging.rename(target)
    else:
        os.link(staging, target)
        staging.unlink()


def publish_image(
    directory: Path,
    call_id: str,
    ordinal: int,
    ffmpeg: Path,
    stop: threading.Event,
    *,
    synthetic: bool = False,
    url: str | None = None,
) -> dict[str, Any]:
    identifier(call_id)
    if type(ordinal) is not int or not 0 <= ordinal < 8 or synthetic == (url is not None):
        raise ProjectError("RESULT_MEDIA_INVALID", 422)
    checked_path(directory)
    for name in (".media-staging", "media"):
        folder = directory / name
        folder.mkdir(exist_ok=True)
        checked_path(folder)
    media_id = str(
        UUID(bytes=hashlib.sha256(f"{call_id}:{ordinal}".encode()).digest()[:16], version=4)
    )
    relative = f"media/{media_id}.image"
    target = relative_file(directory, relative)
    staging = relative_file(directory, f".media-staging/{media_id}.part")
    journal = relative_file(directory, f".media-staging/{media_id}.json")
    fingerprint = hashlib.sha256(
        (url if url is not None else "synthetic-png-v1").encode()
    ).hexdigest()
    if stop.is_set():
        raise ProjectError("JOB_INTERRUPTED")
    if journal.exists():
        try:
            if journal.stat().st_size > 4096:
                raise ValueError
            record = json.loads(journal.read_text("utf-8"))
            if (
                record["id"] != media_id
                or record["relativePath"] != relative
                or record["sourceFingerprint"] != fingerprint
                or record["callId"] != call_id
                or type(record["ordinal"]) is not int
                or record["ordinal"] != ordinal
                or record["provenance"] != ("synthetic" if synthetic else "generated")
            ):
                raise ValueError
            source = target if target.exists() else staging
            if source.stat().st_size > 10 * 1024 * 1024:
                raise ProjectError("MEDIA_HASH_MISMATCH")
            if _hash(source) != record["sha256"]:
                raise ProjectError("MEDIA_HASH_MISMATCH")
            if (
                type(record["byteLength"]) is not int
                or not 1 <= record["byteLength"] <= 10 * 1024 * 1024
                or source.stat().st_size != record["byteLength"]
            ):
                raise ValueError
            # Recheck a durable verified file before making it available again.
            metadata = tools.probe_media(ffmpeg, source, stop)
            if any(record[key] != value for key, value in metadata.items()):
                raise ProjectError("MEDIA_HASH_MISMATCH")
            if not target.exists():
                _publish(staging, target)
            return dict(record)
        except (ValueError, TypeError, KeyError, OSError):
            raise ProjectError("MEDIA_RECOVERY_REQUIRED") from None
    if target.exists():
        raise ProjectError("MEDIA_RECOVERY_REQUIRED")
    # Without a verified journal a partial download is retried from the same
    # original result reference. It never triggers another model submission.
    if staging.exists():
        staging.unlink()
    require_space(directory, 10 * 1024 * 1024)
    try:
        if synthetic:
            with staging.open("xb") as output:
                output.write(_synthetic_png())
                output.flush()
                os.fsync(output.fileno())
            expected_mime = "image/png"
        else:
            assert url is not None
            expected_mime = download_image(url, staging)["mime"]
        metadata = tools.probe_media(ffmpeg, staging, stop)
        if metadata["mime"] != expected_mime:
            raise ProjectError("RESULT_MEDIA_INVALID", 422)
        record = {
            "id": media_id,
            "relativePath": relative,
            "sha256": _hash(staging),
            "byteLength": staging.stat().st_size,
            **metadata,
            "provenance": "synthetic" if synthetic else "generated",
            "sourceFingerprint": fingerprint,
            "callId": call_id,
            "ordinal": ordinal,
        }
        # Publish journal atomically first. A crash on either side of the media
        # rename can recover the exact verified bytes without another download.
        journal_tmp = relative_file(directory, f".media-staging/{media_id}.json.part")
        with journal_tmp.open("wb") as output:
            output.write(canonical(record).encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(journal_tmp, journal)
        if stop.is_set():
            raise ProjectError("JOB_INTERRUPTED")
        _publish(staging, target)
        return record
    except BaseException:
        if not journal.exists():
            staging.unlink(missing_ok=True)
        raise


def register(db: sqlite3.Connection, record: dict[str, Any]) -> str:
    """Called in the same transaction as candidate registration/call success."""
    identifier(record["id"])
    if db.execute("SELECT 1 FROM service_calls WHERE id=?", (record["callId"],)).fetchone() is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    existing = db.execute("SELECT * FROM media_files WHERE id=?", (record["id"],)).fetchone()
    if existing:
        if (
            existing["sha256"] != record["sha256"]
            or existing["relative_path"] != record["relativePath"]
        ):
            raise ProjectError("MEDIA_HASH_MISMATCH")
        return str(existing["id"])
    db.execute(
        "INSERT INTO media_files VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            record["id"],
            record["relativePath"],
            record["sha256"],
            record["byteLength"],
            record["mime"],
            record["durationMs"],
            record["width"],
            record["height"],
            "available",
            record["provenance"],
            canonical({"callId": record["callId"], "ordinal": record["ordinal"]}),
        ),
    )
    return str(record["id"])
