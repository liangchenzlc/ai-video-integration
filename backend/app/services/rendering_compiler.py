"""One deterministic FFmpeg compiler for animatics and final MP4 delivery."""

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from app.storage import timeline, tools
from app.storage.errors import ProjectError
from app.storage.paths import checked_path, relative_file

Json = dict[str, Any]
VERSION = "local-ffmpeg-timeline-v1"


def digest_file(path: Path, stop: threading.Event, cancelled: threading.Event) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if stop.is_set() or cancelled.is_set():
                raise ProjectError("JOB_CANCELLED")
            result.update(chunk)
    return result.hexdigest()


def expression(clip: Json, prop: str, default: float, variable: str = "t") -> str:
    points = sorted(
        (p for p in clip["keyframes"] if p["property"] == prop), key=lambda p: p["timeMs"]
    )
    if not points:
        return str(default)
    result = str(points[-1]["value"])
    for left, right in reversed(list(zip(points, points[1:], strict=False))):
        start, end = left["timeMs"] / 1000, right["timeMs"] / 1000
        value = str(left["value"])
        if left["interpolation"] == "linear":
            value += f"+({right['value']}-{left['value']})*({variable}-{start})/({end}-{start})"
        result = f"if(lt({variable},{end}),{value},{result})"
    return f"if(lt({variable},{points[0]['timeMs'] / 1000}),{points[0]['value']},{result})"


def ass_time(ms: int) -> str:
    centiseconds = max(0, (ms + 5) // 10)
    return (
        f"{centiseconds // 360000}:{centiseconds // 6000 % 60:02}:"
        f"{centiseconds // 100 % 60:02}.{centiseconds % 100:02}"
    )


def subtitles_file(plan: Json, resolved: list[Json], path: Path) -> bool:
    content = plan["timeline"]
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {content['width']}",
        f"PlayResY: {content['height']}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Arial,{round(content['height'] * 0.045)},&H00FFFFFF,&H00FFFFFF,"
        "&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,40,1",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    count = 0
    for item in resolved:
        if item["kind"] != "subtitle" or item["muted"]:
            continue
        clip = item["clip"]
        for cue in item.get("content", {}).get("cues", []):
            start = max(clip["inMs"], cue["time"]["startMs"])
            end = min(clip["inMs"] + clip["durationMs"], cue["time"]["endMs"])
            if start >= end:
                continue
            # Plain text only: do not permit user text to inject ASS override commands.
            text = cue["text"].replace("\\", "＼").replace("{", "｛").replace("}", "｝")
            text = text.replace("\r", "").replace("\n", "\\N")
            lines.append(
                f"Dialogue: 0,{ass_time(clip['startMs'] + start - clip['inMs'])},"
                f"{ass_time(clip['startMs'] + end - clip['inMs'])},Default,,0,0,0,,{text}"
            )
            count += 1
    if count:
        path.write_text("\n".join(lines), encoding="utf-8")
    return bool(count)


def filter_path(path: Path) -> str:
    # Two parsers consume escaping: the filtergraph, then the filter's option parser.
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")


def compile_args(
    plan: Json,
    resolved: list[Json],
    directory: Path,
    ffmpeg: Path,
    output: Path,
    subtitle_path: Path,
    *,
    tool_version: str | None = None,
) -> list[str]:
    content = plan["timeline"]
    fps = content["fps"]["numerator"] / content["fps"]["denominator"]
    count = timeline.frame(content["durationMs"], content["fps"])
    duration = count / fps
    width, height = content["width"], content["height"]
    args = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "info",
        "-nostats",
        "-xerror",
        "-nostdin",
        "-y",
        "-filter_complex_threads",
        "1",
    ]
    graph = [f"color=c=black:s={width}x{height}:r={fps}:d={duration},format=rgba[base]"]
    inputs: dict[str, int] = {}
    for item in resolved:
        if item["muted"] or item["kind"] == "subtitle":
            continue
        clip = item["clip"]
        inputs[clip["id"]] = len(inputs)
        args.extend(
            [
                "-threads",
                "1",
                "-protocol_whitelist",
                "file,pipe",
                "-format_whitelist",
                "image2," + tools.FORMATS if item["kind"] == "image" else tools.FORMATS,
                "-max_pixels",
                str(tools.MAX_PIXELS),
            ]
        )
        if item["kind"] == "image":
            args.extend(
                [
                    "-f",
                    "image2",
                    "-pattern_type",
                    "none",
                    "-loop",
                    "1",
                    "-framerate",
                    str(fps),
                ]
            )
        args.extend(["-i", str(relative_file(directory, item["relativePath"]))])
    base = "base"
    audio = []
    tracks = {t["id"]: t for t in content["tracks"]}
    ordered = sorted(
        resolved,
        key=lambda item: (
            tracks[item["clip"]["trackId"]]["order"],
            item["clip"]["startMs"],
            item["clip"]["id"],
        ),
    )
    for position, item in enumerate(ordered):
        if item["muted"] or item["kind"] == "subtitle":
            continue
        clip, kind = item["clip"], item["kind"]
        index = inputs[clip["id"]]
        start_frame = timeline.frame(clip["startMs"], content["fps"])
        end_frame = timeline.frame(clip["startMs"] + clip["durationMs"], content["fps"])
        length, start = (end_frame - start_frame) / fps, start_frame / fps
        if (kind in timeline.AUDIO or kind == "video" and item.get("hasAudio")) and clip[
            "gainDb"
        ] > -96:
            volume = expression(clip, "volume", 1)
            gain = 10 ** (clip["gainDb"] / 20)
            # Audio time is sample based: preserve the complete selected recording, never retime it.
            delay = round(clip["startMs"] * 48)
            graph.append(
                f"[{index}:a:0]atrim=start={clip['inMs'] / 1000}:end={clip['outMs'] / 1000},"
                f"asetpts=PTS-STARTPTS,aresample=48000,volume='{gain}*({volume})':eval=frame,"
                f"adelay={delay}S:all=1[a{position}]"
            )
            audio.append(f"[a{position}]")
        if kind in timeline.AUDIO:
            continue
        source_trim = (
            ""
            if kind == "image"
            else f"trim=start={clip['inMs'] / 1000}:end={clip['outMs'] / 1000},"
        )
        scale = expression(clip, "scale", 1)
        opacity = expression(clip, "opacity", 1, "T")
        graph.append(
            f"[{index}:v:0]{source_trim}setpts=PTS-STARTPTS,fps={fps},"
            f"trim=end_frame={end_frame - start_frame},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,format=rgba,"
            f"scale=w='max(2,trunc({width}*({scale})/2)*2)':"
            f"h='max(2,trunc({height}*({scale})/2)*2)':eval=frame,"
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({opacity})'[v{position}raw]"
        )
        fades = []
        for transition in content["transitions"]:
            fade_duration = transition["durationMs"] / 1000
            if transition["toClipId"] == clip["id"] and transition["type"] in {"fade", "dissolve"}:
                fades.append(f"fade=t=in:st=0:d={fade_duration}:alpha=1")
            if transition["fromClipId"] == clip["id"] and transition["type"] == "fade":
                fades.append(
                    f"fade=t=out:st={max(0, length - fade_duration)}:d={fade_duration}:alpha=1"
                )
        graph.append(
            f"[v{position}raw]"
            + (",".join(fades) + "," if fades else "")
            + f"setpts=PTS+{start}/TB[v{position}]"
        )
        x = expression(clip, "x", 0, f"(t-{start})")
        y = expression(clip, "y", 0, f"(t-{start})")
        graph.append(
            f"[{base}][v{position}]overlay=x='(W-w)/2+({x})':y='(H-h)/2+({y})':"
            f"eof_action=pass:repeatlast=0:enable='gte(t,{start})*lt(t,{end_frame / fps})'"
            f"[o{position}]"
        )
        base = f"o{position}"
    if content["burnSubtitles"] and subtitles_file(plan, resolved, subtitle_path):
        graph.append(f"[{base}]subtitles=filename='{filter_path(subtitle_path)}'[subbed]")
        base = "subbed"
    graph.append(f"[{base}]format=yuv420p[vout]")
    filter_file = subtitle_path.with_suffix(".filters.txt")
    major = re.match(r"^(\d+)(?:\.|$)", tool_version or "")
    filter_option = (
        "-/filter_complex"
        if major and int(major[1]) >= 7
        else "-filter_complex_script"
        if major
        else "-filter_complex"
    )
    args.extend([filter_option, str(filter_file), "-map", "[vout]"])
    if plan["audioCodec"] is not None:
        graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={duration}[silence]")
        graph.append(
            "[silence]"
            + "".join(audio)
            + f"amix=inputs={len(audio) + 1}:normalize=0:duration=first,"
            + f"atrim=duration={duration},"
            + "astats=metadata=0:reset=0:measure_perchannel=none:measure_overall=Peak_level[aout]"
        )
        args.extend(["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"])
    args.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-threads",
            "1",
            "-r",
            str(fps),
            "-frames:v",
            str(count),
            "-t",
            str(duration),
            "-movflags",
            "+faststart",
            "-f",
            "mp4",
            str(output),
        ]
    )
    if major:
        checked_path(filter_file if filter_file.exists() else filter_file.parent, directory=False)
        filter_file.write_text(";".join(graph), encoding="utf-8")
    else:
        args[args.index(filter_option) + 1] = ";".join(graph)
    if os.name == "nt" and sum(len(arg) + 3 for arg in args) > 30000:
        raise ProjectError("RENDER_SIZE_LIMIT", 422)
    return args


def resolve_native_audio(
    ffmpeg: Path,
    resolved: list[Json],
    directory: Path,
    stop: threading.Event,
    cancelled: threading.Event,
) -> None:
    probe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    known: dict[str, bool] = {}
    for item in resolved:
        if item["kind"] != "video" or item["muted"]:
            continue
        if item["mediaId"] not in known:
            raw = tools.run(
                [
                    str(probe),
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-format_whitelist",
                    tools.FORMATS,
                    "-select_streams",
                    "a",
                    "-show_entries",
                    "stream=index",
                    "-of",
                    "json",
                    str(relative_file(directory, item["relativePath"])),
                ],
                stop,
                cancelled=cancelled,
            )
            known[item["mediaId"]] = bool(json.loads(raw).get("streams"))
        item["hasAudio"] = known[item["mediaId"]]


def verify_mix(log: str, has_audio: bool) -> None:
    if not has_audio:
        return
    levels = re.findall(r"Peak level dB:\s*(-?inf|[-+0-9.]+)", log)
    if not levels:
        raise ProjectError("AUDIO_VERIFICATION_FAILED")
    if any(float(level) >= 0 for level in levels):
        raise ProjectError("AUDIO_CLIPPING")


def verify(
    ffmpeg: Path, output: Path, plan: Json, stop: threading.Event, cancelled: threading.Event
) -> Json:
    content = plan["timeline"]
    info = tools.probe_media(ffmpeg, output, stop, cancelled)
    if info["width"] != content["width"] or info["height"] != content["height"]:
        raise ProjectError("RENDER_VERIFICATION_FAILED")
    probe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    raw = tools.run(
        [
            str(probe),
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-count_frames",
            "-show_streams",
            "-of",
            "json",
            str(output),
        ],
        stop,
        timeout=600,
        cancelled=cancelled,
    )
    streams = json.loads(raw)["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    audio = [s for s in streams if s["codec_type"] == "audio"]
    expected = timeline.frame(content["durationMs"], content["fps"])
    num, den = (int(v) for v in video["avg_frame_rate"].split("/"))
    if (
        video["codec_name"] != "h264"
        or int(video["nb_read_frames"]) != expected
        or num * content["fps"]["denominator"] != den * content["fps"]["numerator"]
        or bool(audio) != (plan["audioCodec"] is not None)
        or any(s["codec_name"] != "aac" for s in audio)
        or video.get("sample_aspect_ratio") not in {"1:1", None}
    ):
        raise ProjectError("RENDER_VERIFICATION_FAILED")
    fps = content["fps"]["numerator"] / content["fps"]["denominator"]
    if abs(info["durationMs"] - expected / fps * 1000) > max(50, 1000 / fps):
        raise ProjectError("RENDER_VERIFICATION_FAILED")
    for stream in audio:
        if (
            int(stream["sample_rate"]) != 48000
            or stream["channels"] != 2
            or abs(float(stream["duration"]) * 1000 - expected / fps * 1000) > 50
        ):
            raise ProjectError("RENDER_VERIFICATION_FAILED")
    return info
