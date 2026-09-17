"""Frozen render plans, durable local work and atomic native-grant publication."""

import copy
import errno
import hashlib
import json
import os
import queue
import shutil
import sqlite3
import threading
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, Concatenate
from uuid import uuid4

from app.services import rendering_compiler as compiler
from app.storage import checks, media, revisions, timeline, tools
from app.storage.database import connect
from app.storage.errors import ProjectError
from app.storage.paths import checked_path, relative_file
from app.storage.settings import canonical
from app.storage.task_plans import identifier

if TYPE_CHECKING:
    from app.services.projects import ProjectService

Json = dict[str, Any]
DATABASE = "project.sqlite3"


def guarded[**P, R](
    method: Callable[Concatenate["RenderingService", P], R],
) -> Callable[Concatenate["RenderingService", P], R]:
    @wraps(method)
    def call(self: "RenderingService", /, *args: P.args, **kwargs: P.kwargs) -> R:
        with self.owner._mutex:
            try:
                return method(self, *args, **kwargs)
            except ProjectError:
                raise
            except (OSError, sqlite3.Error):
                raise ProjectError("STORAGE_UNAVAILABLE", 503) from None
            except (KeyError, TypeError, ValueError):
                raise ProjectError("VALIDATION_FAILED", 422) from None

    return call


def require_production_checks(
    db: sqlite3.Connection, revision_id: str, *, burn_subtitles: bool | None = None
) -> None:
    from app.storage import production_audio_checks, rendering_checks

    target = revisions.get(db, revision_id)
    # Reports belong to the immutable adopted revision. Admission additionally evaluates
    # the exact output switches; disabling captions must not reuse caption-carrier evidence.
    if burn_subtitles is not None:
        target = copy.deepcopy(target)
        target["payload"]["content"]["burnSubtitles"] = burn_subtitles
    latest: dict[str, Json] = {}
    for row in db.execute("SELECT report_json FROM check_runs ORDER BY rowid"):
        report = json.loads(row[0])
        if (
            report["method"] == "local"
            and report["ruleVersion"] == checks.VERSION
            and revision_id in report["revisionIds"]
        ):
            for rule in report["ruleIds"]:
                latest[rule] = report
    for rule in checks.PRODUCTION_RULES:
        report = latest.get(rule)
        if report is None or report["outcome"] not in {"pass", "not_applicable"}:
            raise ProjectError("CHECK_REQUIRED")
        evaluator = (
            rendering_checks.evaluate
            if rule in rendering_checks.RULES
            else production_audio_checks.evaluate
        )
        if evaluator(db, target, rule)["outcome"] not in {"pass", "not_applicable"}:
            raise ProjectError("CHECK_BLOCKED")


def confirmed_chain(
    db: sqlite3.Connection, revision_id: str, seen: set[str] | None = None
) -> list[str]:
    seen = set() if seen is None else seen
    if revision_id in seen:
        return []
    seen.add(revision_id)
    revision = revisions.get(db, revision_id)
    artifact = revisions.artifact(db, revision["artifactId"])
    if (
        artifact["adoptedRevisionId"] != revision_id
        or artifact["confirmedRevisionId"] != revision_id
        or artifact["needsUpdate"]
    ):
        raise ProjectError("CHECK_REQUIRED")
    checks.require_coverage(db, revision_id)
    if db.execute(
        "SELECT 1 FROM checks WHERE revision_id=? "
        "AND severity IN ('blocking','unknown_required') AND status!='resolved'",
        (revision_id,),
    ).fetchone():
        raise ProjectError("CHECK_BLOCKED")
    result = [revision_id]
    for row in db.execute(
        "SELECT DISTINCT from_revision_id FROM dependencies WHERE to_revision_id=?", (revision_id,)
    ):
        result.extend(confirmed_chain(db, row[0], seen))
    return result


def build_plan(
    db: sqlite3.Connection, revision_id: str, purpose: str, burn: bool | None = None
) -> tuple[Json, list[Json]]:
    revision = revisions.get(db, revision_id)
    if revision["payload"]["kind"] != "timeline":
        raise ProjectError("VALIDATION_FAILED", 422)
    adopted = revisions.artifact(db, revision["artifactId"])
    if adopted["adoptedRevisionId"] != revision_id:
        raise ProjectError("TIMELINE_NOT_ADOPTED")
    content = copy.deepcopy(revision["payload"]["content"])
    if burn is not None:
        content["burnSubtitles"] = burn
    timeline.validate(content, db, coverage=True)
    if content["durationMs"] > 60 * 60 * 1000 or len(content["clips"]) > 1000:
        raise ProjectError("RENDER_SIZE_LIMIT", 422)
    tracks = {t["id"]: t for t in content["tracks"]}
    hashes: dict[str, str] = {}
    resolved = []
    for clip in content["clips"]:
        track = tracks[clip["trackId"]]
        item = {"clip": copy.deepcopy(clip), "kind": track["kind"], "muted": track["muted"]}
        media_id = clip["mediaId"]
        if clip["contentRevisionId"]:
            source = revisions.get(db, clip["contentRevisionId"])
            item["content"] = source["payload"]["content"]
            item["contentHash"] = source["contentHash"]
            media_id = (
                media_id or item["content"].get("mediaId") or item["content"].get("videoMediaId")
            )
        if track["kind"] == "subtitle":
            if not item.get("content", {}).get("cues"):
                raise ProjectError("SUBTITLE_CONTENT_REQUIRED", 422)
        else:
            row = media.media_row(db, media_id)
            hashes[media_id] = row["sha256"]
            item.update(mediaId=media_id, relativePath=row["relative_path"], sha256=row["sha256"])
        resolved.append(item)
    plan = {
        "id": str(uuid4()),
        "compilerVersion": compiler.VERSION,
        "timelineRevisionId": revision_id,
        "timeline": content,
        "mediaHashes": [{"mediaId": key, "sha256": value} for key, value in sorted(hashes.items())],
        "videoCodec": "h264",
        "audioCodec": "aac"
        if any(i["kind"] in timeline.AUDIO | {"video"} and not i["muted"] for i in resolved)
        else None,
        "purpose": purpose,
    }
    # Purpose does not change encoder settings; preview and export share the same compiler.
    inputs = {
        "compiler": compiler.VERSION,
        "timelineHash": revision["contentHash"],
        "timeline": content,
        "mediaHashes": plan["mediaHashes"],
        "contentHashes": [i.get("contentHash") for i in resolved],
        "videoCodec": plan["videoCodec"],
        "audioCodec": plan["audioCodec"],
    }
    plan["inputHash"] = hashlib.sha256(canonical(inputs).encode("utf-8")).hexdigest()
    return plan, resolved


class RenderingService:
    def __init__(self, owner: "ProjectService") -> None:
        self.owner = owner
        self.stop = threading.Event()
        self.pending: dict[tuple[Path, str], threading.Event] = {}
        self.tasks: queue.Queue[tuple[Path, str, str] | None] = queue.Queue()
        self.thread: threading.Thread | None = None

    @guarded
    def preview_render_plan(
        self, project_id: str, session_id: str, window_id: int, payload: Json
    ) -> Json:
        return self.owner._versions.read(
            project_id,
            session_id,
            window_id,
            lambda db, _: build_plan(
                db, payload["timelineRevisionId"], "preview", payload.get("burnSubtitles")
            )[0],
        )

    @guarded
    def get_render_plan(
        self, project_id: str, session_id: str, window_id: int, plan_id: str
    ) -> Json:
        def action(db: sqlite3.Connection, _: sqlite3.Row) -> Json:
            row = db.execute(
                "SELECT plan_json FROM render_plans WHERE id=?", (identifier(plan_id),)
            ).fetchone()
            if row is None:
                raise ProjectError("OBJECT_NOT_FOUND", 404)
            result: Json = json.loads(row[0])
            return result

        return self.owner._versions.read(project_id, session_id, window_id, action)

    @guarded
    def edit_timeline(
        self, project_id: str, session_id: str, window_id: int, payload: Json
    ) -> Json:
        def action(db: sqlite3.Connection, _: sqlite3.Row) -> Json:
            result = timeline.edit(payload)
            timeline.validate(result["timeline"], db)
            return result

        return self.owner._versions.read(project_id, session_id, window_id, action)

    @guarded
    def replacement_preview(
        self, project_id: str, session_id: str, window_id: int, payload: Json
    ) -> Json:
        def action(db: sqlite3.Connection, _: sqlite3.Row) -> Json:
            revision = revisions.get(db, payload["timelineRevisionId"])
            if revision["payload"]["kind"] != "timeline":
                raise ProjectError("VALIDATION_FAILED", 422)
            content = revision["payload"]["content"]
            affected = timeline.linked(content, payload["clipId"])
            clip = next(c for c in content["clips"] if c["id"] == payload["clipId"])
            row = media.media_row(db, payload["newMediaId"])
            track = next(t for t in content["tracks"] if t["id"] == clip["trackId"])
            correct = row["availability"] == "available" and (
                (track["kind"] == "image" and row["mime"].startswith("image/"))
                or (track["kind"] == "video" and row["mime"] == "video/mp4")
                or (
                    track["kind"] in timeline.AUDIO and row["mime"].startswith(("audio/", "video/"))
                )
            )
            shortage = (
                0
                if row["mime"].startswith("image/")
                else max(0, clip["outMs"] - (row["duration_ms"] or 0))
            )
            return {
                "shortageMs": shortage,
                "affectedClipIds": sorted(affected),
                "requiredChecks": ["media.available", "timeline.bounds", "dialogue.timing"],
                "canPreserveEdit": correct and shortage == 0,
            }

        return self.owner._versions.read(project_id, session_id, window_id, action)

    @guarded
    def render_animatic(
        self, project_id: str, session_id: str, window_id: int, command: Json
    ) -> Json:
        return self._submit(project_id, session_id, window_id, command, "animatic")

    @guarded
    def export_film(self, project_id: str, session_id: str, window_id: int, command: Json) -> Json:
        return self._submit(project_id, session_id, window_id, command, "export")

    def _submit(
        self, project_id: str, session_id: str, window_id: int, command: Json, kind: str
    ) -> Json:
        with self.owner._mutex:
            session = self.owner._draft_session(project_id, session_id, window_id)
            created_job: list[str] = []

            def action(db: sqlite3.Connection, _: sqlite3.Row, payload: Json) -> str:
                if db.execute(
                    "SELECT 1 FROM local_jobs WHERE heavy=1 AND state IN ('queued','running')"
                ).fetchone():
                    raise ProjectError("PROJECT_BUSY")
                target = None
                chain = []
                if kind == "export":
                    chain = confirmed_chain(db, payload["timelineRevisionId"])
                    require_production_checks(
                        db,
                        payload["timelineRevisionId"],
                        burn_subtitles=payload["burnSubtitles"],
                    )
                    target = self.owner._grant(payload["targetGrantId"], "exportFilm", window_id)
                    if target.exists() and not payload["overwriteConfirmed"]:
                        raise ProjectError("OVERWRITE_CONFIRMATION_REQUIRED")
                    if target.resolve().is_relative_to(session.directory.resolve()):
                        raise ProjectError("EXPORT_TARGET_IN_PROJECT", 422)
                plan, resolved = build_plan(
                    db, payload["timelineRevisionId"], kind, payload.get("burnSubtitles")
                )
                with connect(self.owner._application, "ro") as app:
                    configured = app.execute(
                        "SELECT ffmpeg_path,ffmpeg_probe_json FROM settings"
                    ).fetchone()
                    ffmpeg = configured[0]
                    ffmpeg_version = json.loads(configured[1] or "{}").get("version")
                if not ffmpeg:
                    raise ProjectError("MEDIA_TOOLS_UNAVAILABLE", 422)
                job_id, export_id, media_id = str(uuid4()), str(uuid4()), str(uuid4())
                snapshot = {
                    "timelineRevisionId": payload["timelineRevisionId"],
                    "plan": plan,
                    "resolved": resolved,
                    "ffmpegPath": ffmpeg,
                    "ffmpegVersion": ffmpeg_version,
                    "targetPath": str(target) if target else None,
                    "overwriteConfirmed": payload.get("overwriteConfirmed", False),
                    "exportId": export_id if kind == "export" else None,
                    "mediaId": media_id,
                    "chainRevisionIds": chain,
                    "checkReports": [
                        json.loads(row[0])
                        for row in db.execute("SELECT report_json FROM check_runs")
                        if any(rid in json.loads(row[0])["revisionIds"] for rid in chain)
                    ],
                }
                db.execute(
                    "INSERT INTO render_plans(id,timeline_revision_id,plan_json,input_hash) "
                    "VALUES(?,?,?,?)",
                    (plan["id"], payload["timelineRevisionId"], canonical(plan), plan["inputHash"]),
                )
                db.execute(
                    "INSERT INTO local_jobs VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        job_id,
                        kind,
                        "queued",
                        1,
                        0,
                        canonical(snapshot),
                        None,
                        None,
                        command["clientOperationId"],
                    ),
                )
                if kind == "export":
                    db.execute(
                        "INSERT INTO exports(id,timeline_revision_id,job_id,state,media_id,"
                        "input_hash) VALUES(?,?,?,?,?,?)",
                        (
                            export_id,
                            payload["timelineRevisionId"],
                            job_id,
                            "pending",
                            None,
                            plan["inputHash"],
                        ),
                    )
                created_job.append(job_id)
                return export_id if kind == "export" else job_id

            fields = (
                {"timelineRevisionId"}
                if kind == "animatic"
                else {"timelineRevisionId", "targetGrantId", "burnSubtitles", "overwriteConfirmed"}
            )
            receipt = self.owner._versions.write(
                project_id,
                session_id,
                window_id,
                command,
                "renderAnimatic" if kind == "animatic" else "exportFilm",
                fields,
                None,
                action,
            )
            if created_job:
                self.enqueue(session.directory, created_job[0], project_id)
            return receipt

    @guarded
    def get_export(self, project_id: str, session_id: str, window_id: int, export_id: str) -> Json:
        def action(db: sqlite3.Connection, _: sqlite3.Row) -> Json:
            row = db.execute(
                "SELECT * FROM exports WHERE id=?", (identifier(export_id),)
            ).fetchone()
            if row is None:
                raise ProjectError("OBJECT_NOT_FOUND", 404)
            return {
                "id": row["id"],
                "timelineRevisionId": row["timeline_revision_id"],
                "jobId": row["job_id"],
                "state": row["state"],
                "mediaId": row["media_id"],
                "inputHash": row["input_hash"],
            }

        return self.owner._versions.read(project_id, session_id, window_id, action)

    def enqueue(self, directory: Path, job_id: str, project_id: str) -> None:
        if self.stop.is_set() or (directory, job_id) in self.pending:
            return
        self.pending[(directory, job_id)] = threading.Event()
        self.tasks.put((directory, job_id, project_id))
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, daemon=True, name="local-render")
            self.thread.start()

    def recover(self, directory: Path, project_id: str) -> None:
        with connect(directory / DATABASE, "ro") as db:
            self.owner._project_row(db, project_id)
            ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM local_jobs WHERE kind IN ('animatic','export') "
                    "AND state IN ('queued','running')"
                )
            ]
        for job_id in ids:
            self.enqueue(directory, job_id, project_id)

    def busy(self, directory: Path) -> bool:
        return any(path == directory for path, _ in self.pending)

    def cancel(self, directory: Path, job_id: str) -> None:
        event = self.pending.get((directory, job_id))
        if event:
            event.set()
        with connect(directory / DATABASE) as db, db:
            db.execute(
                "UPDATE exports SET state='cancelled' WHERE job_id=? AND state='pending'", (job_id,)
            )

    def shutdown(self) -> None:
        self.stop.set()
        self.tasks.put(None)
        if self.thread:
            self.thread.join(timeout=3)

    def _loop(self) -> None:
        while (item := self.tasks.get()) is not None:
            directory, job_id, project_id = item
            try:
                if not self.stop.is_set():
                    self._execute(directory, job_id, project_id, self.pending[(directory, job_id)])
            except Exception as error:
                code = (
                    error.code
                    if isinstance(error, ProjectError)
                    else "INSUFFICIENT_DISK_SPACE"
                    if isinstance(error, OSError) and error.errno == errno.ENOSPC
                    else "RENDER_FAILED"
                )
                with self.owner._mutex, connect(directory / DATABASE) as db, db:
                    if not self.stop.is_set():
                        db.execute(
                            "UPDATE local_jobs SET state='failed',active=0,error_code=? "
                            "WHERE id=? AND state NOT IN ('cancelled','succeeded')",
                            (code, job_id),
                        )
                        db.execute(
                            "UPDATE exports SET state='failed' WHERE job_id=? AND state='pending'",
                            (job_id,),
                        )
            finally:
                with self.owner._mutex:
                    self.pending.pop((directory, job_id), None)
                    self.owner._media_finished(directory)

    def _execute(
        self, directory: Path, job_id: str, project_id: str, cancelled: threading.Event
    ) -> None:
        with self.owner._mutex, connect(directory / DATABASE) as db, db:
            self.owner._project_row(db, project_id)
            job = db.execute("SELECT * FROM local_jobs WHERE id=?", (job_id,)).fetchone()
            if job is None or job["state"] not in {"queued", "running"}:
                return
            snapshot = json.loads(job["snapshot_json"])
            db.execute("UPDATE local_jobs SET state='running',active=1 WHERE id=?", (job_id,))
        plan, resolved = snapshot["plan"], snapshot["resolved"]
        ffmpeg = Path(snapshot["ffmpegPath"])
        export_directory = directory / "exports"
        export_directory.mkdir(exist_ok=True)
        checked_path(export_directory)
        output = relative_file(directory, f"exports/{job_id}.mp4")
        temporary = relative_file(directory, f"exports/{job_id}.encoding.mp4")
        manifest = relative_file(directory, f"exports/{job_id}.manifest.json")
        subtitle_path = relative_file(directory, f"exports/{job_id}.ass")
        if not output.exists():
            media.require_space(
                directory,
                max(1024 * 1024, min(tools.MAX_BYTES, plan["timeline"]["durationMs"] * 2000)),
            )
            for item in resolved:
                if item.get("mediaId") and not item["muted"]:
                    source = relative_file(directory, item["relativePath"])
                    if compiler.digest_file(source, self.stop, cancelled) != item["sha256"]:
                        raise ProjectError("MEDIA_HASH_MISMATCH")
            if not self._copy_cached(directory, plan["inputHash"], temporary, cancelled):
                compiler.resolve_native_audio(ffmpeg, resolved, directory, self.stop, cancelled)
                log = tools.run(
                    compiler.compile_args(
                        plan,
                        resolved,
                        directory,
                        ffmpeg,
                        temporary,
                        subtitle_path,
                        tool_version=snapshot.get("ffmpegVersion"),
                    ),
                    self.stop,
                    timeout=max(120, plan["timeline"]["durationMs"] / 1000 * 30),
                    cancelled=cancelled,
                )
                compiler.verify_mix(log, plan["audioCodec"] is not None)
            info = compiler.verify(ffmpeg, temporary, plan, self.stop, cancelled)
            output_hash = compiler.digest_file(temporary, self.stop, cancelled)
            manifest_value = {
                "jobId": job_id,
                "mediaId": snapshot["mediaId"],
                "inputHash": plan["inputHash"],
                "sha256": output_hash,
                "byteLength": temporary.stat().st_size,
                "probe": info,
            }
            self._write_manifest(manifest, manifest_value)
            if cancelled.is_set() or self.stop.is_set():
                raise ProjectError("JOB_CANCELLED")
            with temporary.open("r+b") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, output)
        else:
            if not manifest.exists():
                raise ProjectError("RENDER_RECOVERY_REQUIRED")
            manifest_value = json.loads(manifest.read_text("utf-8"))
            if (
                manifest_value["jobId"] != job_id
                or manifest_value["inputHash"] != plan["inputHash"]
                or compiler.digest_file(output, self.stop, cancelled) != manifest_value["sha256"]
            ):
                raise ProjectError("RENDER_RECOVERY_REQUIRED")
            info = compiler.verify(ffmpeg, output, plan, self.stop, cancelled)
        # Internal canonical media is durable even when external delivery fails.
        with self.owner._mutex, connect(directory / DATABASE) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO media_files VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    snapshot["mediaId"],
                    f"exports/{job_id}.mp4",
                    manifest_value["sha256"],
                    output.stat().st_size,
                    info["mime"],
                    info["durationMs"],
                    info["width"],
                    info["height"],
                    "available",
                    "derived",
                    canonical(
                        {
                            "jobId": job_id,
                            "renderPlanId": plan["id"],
                            "inputHash": plan["inputHash"],
                            "purpose": plan["purpose"],
                            "limitations": "Technical encoding verification only; "
                            "no artistic or semantic acceptance.",
                        }
                    ),
                ),
            )
            if snapshot["exportId"]:
                db.execute(
                    "UPDATE exports SET media_id=? WHERE id=?",
                    (snapshot["mediaId"], snapshot["exportId"]),
                )
        if snapshot["targetPath"]:
            self._publish(
                output,
                Path(snapshot["targetPath"]),
                manifest_value["sha256"],
                job_id,
                snapshot["overwriteConfirmed"],
                cancelled,
                directory,
                manifest,
                manifest_value,
            )
        with self.owner._mutex, connect(directory / DATABASE) as db, db:
            self.owner._project_row(db, project_id)
            state = db.execute("SELECT state FROM local_jobs WHERE id=?", (job_id,)).fetchone()[0]
            if state == "cancelled" or cancelled.is_set() or self.stop.is_set():
                return
            db.execute(
                "UPDATE local_jobs SET state='succeeded',active=0,result_id=?,"
                "error_code=NULL WHERE id=?",
                (snapshot["exportId"] or snapshot["mediaId"], job_id),
            )
            if snapshot["exportId"]:
                db.execute(
                    "UPDATE exports SET state='complete' WHERE id=?", (snapshot["exportId"],)
                )

    def _copy_cached(
        self, directory: Path, input_hash: str, target: Path, cancelled: threading.Event
    ) -> bool:
        with connect(directory / DATABASE, "ro") as db:
            candidates = db.execute(
                "SELECT relative_path,sha256 FROM media_files WHERE availability='available' "
                "AND provenance='derived' AND json_extract(source_json,'$.inputHash')=?",
                (input_hash,),
            ).fetchall()
        for candidate in candidates:
            source = relative_file(directory, candidate["relative_path"])
            if not source.is_file():
                continue
            if compiler.digest_file(source, self.stop, cancelled) != candidate["sha256"]:
                continue
            with source.open("rb") as incoming, target.open("wb") as outgoing:
                while chunk := incoming.read(1024 * 1024):
                    if self.stop.is_set() or cancelled.is_set():
                        raise ProjectError("JOB_CANCELLED")
                    outgoing.write(chunk)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if compiler.digest_file(target, self.stop, cancelled) != candidate["sha256"]:
                raise ProjectError("RENDER_VERIFICATION_FAILED")
            return True
        return False

    @staticmethod
    def _write_manifest(path: Path, value: Json) -> None:
        temporary = path.with_suffix(".writing.json")
        checked_path(temporary if temporary.exists() else temporary.parent, directory=False)
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def _publish(
        self,
        source: Path,
        target: Path,
        expected_hash: str,
        job_id: str,
        overwrite: bool,
        cancelled: threading.Event,
        directory: Path,
        manifest: Path,
        value: Json,
    ) -> None:
        checked_path(target.parent)
        if target.resolve().is_relative_to(directory.resolve()) or target.suffix.lower() != ".mp4":
            raise ProjectError("GRANT_REJECTED", 403)
        if target.exists():
            checked_path(target, directory=False)
            if (
                value.get("publicationPrepared")
                and compiler.digest_file(target, self.stop, cancelled) == expected_hash
            ):
                return
            if not overwrite:
                raise ProjectError("OVERWRITE_CONFIRMATION_REQUIRED")
        temporary = target.parent / f".avi-{job_id}.publishing.mp4"
        checked_path(temporary if temporary.exists() else temporary.parent, directory=False)
        try:
            if shutil.disk_usage(target.parent).free < source.stat().st_size + 16 * 1024**2:
                raise ProjectError("INSUFFICIENT_DISK_SPACE", 507)
            with source.open("rb") as incoming, temporary.open("wb") as outgoing:
                while chunk := incoming.read(1024 * 1024):
                    if cancelled.is_set() or self.stop.is_set():
                        raise ProjectError("JOB_CANCELLED")
                    outgoing.write(chunk)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if compiler.digest_file(temporary, self.stop, cancelled) != expected_hash:
                raise ProjectError("RENDER_VERIFICATION_FAILED")
            value["publicationPrepared"] = True
            self._write_manifest(manifest, value)
            with self.owner._mutex:
                if cancelled.is_set() or self.stop.is_set():
                    raise ProjectError("JOB_CANCELLED")
                checked_path(target.parent)
                if target.exists():
                    checked_path(target, directory=False)
                if overwrite:
                    os.replace(temporary, target)
                elif os.name == "nt":
                    # Windows rename refuses an existing target and also works on FAT/exFAT.
                    os.rename(temporary, target)
                else:
                    # Hard-link publication is atomic and refuses a racing existing target.
                    os.link(temporary, target)
                    temporary.unlink()
                # The rename and state change share the cancellation mutex. Recovery handles
                # a process crash in between using the prepared publication hash above.
                with connect(directory / DATABASE) as db, db:
                    row = db.execute("SELECT id FROM exports WHERE job_id=?", (job_id,)).fetchone()
                    if row is None:
                        raise ProjectError("RENDER_RECOVERY_REQUIRED")
                    db.execute(
                        "UPDATE local_jobs SET state='succeeded',active=0,result_id=?,"
                        "error_code=NULL WHERE id=?",
                        (row[0], job_id),
                    )
                    db.execute("UPDATE exports SET state='complete' WHERE job_id=?", (job_id,))
        finally:
            if temporary.exists():
                checked_path(temporary, directory=False)
                temporary.unlink()
