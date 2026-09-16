"""Explicitly selected local tools, bounded subprocesses and media verification."""

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from app.storage.errors import ProjectError
from app.storage.paths import checked_path

MAX_BYTES = 2 * 1024**3
MAX_PIXELS = 40_000_000
TIMEOUT = 15.0
DECODE_TIMEOUT = 120.0
OUTPUT_LIMIT = 1024 * 1024
FORMATS = "png_pipe,jpeg_pipe,mov,wav,mp3"
EXTENSIONS = {".png", ".jpg", ".jpeg", ".mp4", ".wav", ".mp3", ".m4a"}


def run(
    argv: list[str],
    stop: threading.Event | None = None,
    *,
    timeout: float | None = None,
    cancelled: threading.Event | None = None,
) -> str:
    """Drain output continuously with a hard cap; never use a shell or expose stderr."""
    try:
        checked_path(Path(argv[0]), directory=False)
    except OSError:
        raise ProjectError("MEDIA_TOOLS_UNAVAILABLE", 422) from None
    output = bytearray()
    overflow = threading.Event()
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
    except OSError:
        raise ProjectError("MEDIA_TOOLS_UNAVAILABLE", 422) from None

    def drain() -> None:
        assert process.stdout is not None
        while chunk := process.stdout.read(65536):
            remaining = OUTPUT_LIMIT - len(output)
            output.extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow.set()

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    deadline = time.monotonic() + (TIMEOUT if timeout is None else timeout)
    error: str | None = None
    try:
        while process.poll() is None:
            if stop is not None and stop.is_set():
                error = "JOB_INTERRUPTED"
                break
            if cancelled is not None and cancelled.is_set():
                error = "JOB_CANCELLED"
                break
            if overflow.is_set():
                error = "MEDIA_TOOL_OUTPUT_LIMIT"
                break
            if time.monotonic() >= deadline:
                error = "MEDIA_PROBE_TIMEOUT"
                break
            time.sleep(0.01)
        if error:
            process.kill()
        process.wait(timeout=2)
        reader.join(timeout=2)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        if process.stdout:
            process.stdout.close()
    if error or overflow.is_set():
        raise ProjectError(error or "MEDIA_TOOL_OUTPUT_LIMIT", 422)
    decoded = output.decode("utf-8", errors="replace")
    if "exceeds specified max pixel count" in decoded:
        raise ProjectError("MEDIA_PIXEL_LIMIT", 422)
    if process.returncode:
        raise ProjectError("MEDIA_INVALID", 422)
    return decoded


def inspect_tools(ffmpeg: Path) -> dict[str, Any]:
    checked_path(ffmpeg, directory=False)
    if not ffmpeg.is_file() or ffmpeg.name.lower() not in {"ffmpeg", "ffmpeg.exe"}:
        raise ProjectError("MEDIA_TOOLS_UNAVAILABLE", 422)
    probe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if not probe.is_file():
        raise ProjectError("MEDIA_TOOLS_UNAVAILABLE", 422)
    version = run([str(ffmpeg), "-version"])
    probe_version = run([str(probe), "-version"])
    matched = re.search(r"^ffmpeg version (\S+)", version)
    paired = re.search(r"^ffprobe version (\S+)", probe_version)
    if not matched or not paired or matched[1] != paired[1]:
        raise ProjectError("MEDIA_TOOLS_MISMATCH", 422)
    encoders = run([str(ffmpeg), "-hide_banner", "-encoders"])
    filters = run([str(ffmpeg), "-hide_banner", "-filters"])
    if not re.search(r"\blibx264\b", encoders) or not re.search(r"\baac\b", encoders):
        raise ProjectError("MEDIA_TOOLS_CAPABILITY_MISSING", 422)
    if not re.search(r"\bsubtitles\b", filters) or "--enable-libass" not in version:
        raise ProjectError("MEDIA_TOOLS_CAPABILITY_MISSING", 422)
    return {
        "version": matched[1],
        "build": version[:16384],
        "h264": True,
        "aac": True,
        "libass": True,
    }


def probe_media(
    ffmpeg: Path, source: Path, stop: threading.Event, cancelled: threading.Event | None = None
) -> dict[str, Any]:
    probe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    restrictions = ["-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS]
    raw = run(
        [
            str(probe),
            "-v",
            "error",
            *restrictions,
            "-max_pixels",
            str(MAX_PIXELS),
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(source),
        ],
        stop,
        cancelled=cancelled,
    )
    try:
        data = json.loads(raw)
        streams = data["streams"]
        video = next((s for s in streams if s["codec_type"] == "video"), None)
        audio = next((s for s in streams if s["codec_type"] == "audio"), None)
        container = data["format"]["format_name"]
        if not streams or any(s["codec_type"] not in {"video", "audio"} for s in streams):
            raise ValueError
        for stream in streams:
            if stream["codec_type"] != "video":
                continue
            stream_width, stream_height = int(stream["width"]), int(stream["height"])
            if stream_width < 1 or stream_height < 1 or stream_width * stream_height > MAX_PIXELS:
                raise ProjectError("MEDIA_PIXEL_LIMIT", 422)
        width, height = (int(video["width"]), int(video["height"])) if video else (None, None)
        if container in {"png_pipe", "jpeg_pipe"} and video and len(streams) == 1:
            expected = "png" if container == "png_pipe" else "mjpeg"
            if video["codec_name"] != expected:
                raise ValueError
            mime = "image/png" if expected == "png" else "image/jpeg"
            duration = None
        else:
            duration = round(float(data["format"]["duration"]) * 1000)
            if not 1 <= duration <= 9007199254740991:
                raise ValueError
            if container == "wav" and audio and not video:
                mime = "audio/wav"
            elif container == "mp3" and audio and not video:
                mime = "audio/mpeg"
            elif "mp4" in container.split(",") and (video or audio):
                mime = "video/mp4" if video else "audio/mp4"
            else:
                raise ValueError
    except (KeyError, TypeError, ValueError, StopIteration, OverflowError):
        raise ProjectError("MEDIA_INVALID", 422) from None
    # Decode the complete stream after checking dimensions. Corrupt tails must never be available.
    run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-xerror",
            "-nostdin",
            "-threads",
            "1",
            *restrictions,
            "-max_pixels",
            str(MAX_PIXELS),
            "-i",
            str(source),
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-threads",
            "1",
            "-f",
            "null",
            "-",
        ],
        stop,
        timeout=DECODE_TIMEOUT,
        cancelled=cancelled,
    )
    return {"mime": mime, "durationMs": duration, "width": width, "height": height}
