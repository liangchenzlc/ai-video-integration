"""Local, allowlisted diagnostic archives. Never copy logs, databases or credentials."""

import hashlib
import json
import os
import platform
import re
import sqlite3
import zipfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.storage.database import connect
from app.storage.errors import ProjectError
from app.storage.paths import checked_path
from app.storage.settings import canonical

if TYPE_CHECKING:
    from app.services.projects import ProjectService

Json = dict[str, Any]


def redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {
            key: "[已移除]"
            if re.search(
                r"secret|token|password|credential|authorization|api.?key|access.?key|path|url",
                key,
                re.I,
            )
            else redact(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if not isinstance(value, str):
        return value
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            value = value.replace(secret, "[凭据已移除]")
    value = re.sub(r"https?://[^\s\"<>]+", "[链接已移除]", value, flags=re.I)
    value = re.sub(r"(?:[A-Za-z]:[\\/]|\\\\)[^\r\n\"<>]+", "[路径已移除]", value)
    value = re.sub(r"(?i)\b(?:bearer\s+|sk-|sk_)[A-Za-z0-9._/-]+", "[令牌已移除]", value)
    value = re.sub(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|"
        r"xox[baprs]-[A-Za-z0-9-]+|AIza[A-Za-z0-9_-]{20,}|"
        r"(?:AKIA|ASIA)[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)",
        "[令牌已移除]",
        value,
    )
    value = re.sub(
        r"""(?i)["']?(?:api[_ -]?key|access[_ -]?key(?:[_ -]?secret)?|token|password|secret)["']?"""
        r"""\s*[:=]\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;"}]+)""",
        "[秘密字段已移除]",
        value,
    )
    return value


class DiagnosticService:
    def __init__(self, owner: "ProjectService") -> None:
        self.owner = owner

    def _session(self, window: int, session_id: str | None) -> Any:
        if session_id is None:
            raise ProjectError("SESSION_EXPIRED", 401)
        return self.owner._session(session_id, window)

    def preview(self, window: int, payload: Json, session_id: str | None = None) -> Json:
        with self.owner._mutex:
            if payload["includeContent"] and not payload["includeProject"]:
                raise ProjectError("VALIDATION_FAILED", 422)
            if bool(payload["projectId"]) != payload["includeProject"]:
                raise ProjectError("VALIDATION_FAILED", 422)
            files = [
                {
                    "name": "runtime.json",
                    "description": "应用、Python、SQLite与系统版本；不包含日志或本机路径。",
                }
            ]
            if payload["includeProject"]:
                session = self._session(window, session_id)
                if session.project_id != payload["projectId"]:
                    raise ProjectError("SESSION_EXPIRED", 401)
                files.append(
                    {
                        "name": "project-summary.json",
                        "description": "项目格式版本、对象数量与作业状态；不包含项目名称或正文。",
                    }
                )
            if payload["includeContent"]:
                files.append(
                    {
                        "name": "content.json",
                        "description": (
                            "当前草稿正文，移除已配置凭据、令牌、链接和本机路径；仍包含创作内容。"
                        ),
                    }
                )
            return {"files": files, **payload}

    def _secrets(self) -> tuple[str, ...]:
        # Fail closed when an installed credential cannot be decrypted.
        with connect(self.owner._application, "ro") as db:
            providers = {r[0] for r in db.execute("SELECT provider_id FROM credentials")}
        providers.update(self.owner._settings.secrets)
        values: list[str] = []
        for provider in providers:
            for key, value in self.owner._settings.secret(provider).items():
                if key != "kind" and isinstance(value, str) and value:
                    values.append(value)
        return tuple(values)

    def create(self, window: int, command: Json, session_id: str | None = None) -> Json:
        with self.owner._mutex:
            operation, digest = self.owner._command_identity(
                command,
                {"projectId", "includeProject", "includeContent", "targetGrantId"},
            )
            if command["expectedRevision"] != 0:
                raise ProjectError("REVISION_CONFLICT")
            with connect(self.owner._application) as db:
                previous = db.execute(
                    "SELECT * FROM global_operations WHERE id=?", (operation,)
                ).fetchone()
            if previous is not None:
                if (
                    previous["request_hash"] != digest
                    or previous["operation_name"] != "createDiagnostic"
                ):
                    raise ProjectError("OPERATION_ID_REUSED")
                previous_receipt: Json = json.loads(previous["receipt_json"])
                return previous_receipt
            payload = command["payload"]
            self.preview(
                window,
                {k: payload[k] for k in ("projectId", "includeProject", "includeContent")},
                session_id,
            )
            target = self.owner._grant(payload["targetGrantId"], "diagnostic", window)
            if target.exists():
                raise ProjectError("TARGET_EXISTS")
            files: Json = {
                "runtime.json": {
                    "appVersion": "0.1.0",
                    "apiVersion": "1.0.0",
                    "controlVersion": 1,
                    "pythonVersion": platform.python_version(),
                    "sqliteVersion": sqlite3.sqlite_version,
                    "os": platform.system(),
                    "osRelease": platform.release(),
                    "createdAt": datetime.now(UTC).isoformat(),
                }
            }
            if payload["includeProject"]:
                session = self._session(window, session_id)
                with connect(session.directory / "project.sqlite3", "ro") as db:
                    db.execute("BEGIN")
                    files["project-summary.json"] = {
                        "schemaVersion": db.execute("PRAGMA user_version").fetchone()[0],
                        "draftCounts": dict(
                            db.execute("SELECT kind,count(*) FROM drafts GROUP BY kind")
                        ),
                        "mediaCounts": dict(
                            db.execute(
                                "SELECT availability,count(*) FROM media_files "
                                "GROUP BY availability"
                            )
                        ),
                        "jobCounts": dict(
                            db.execute("SELECT state,count(*) FROM local_jobs GROUP BY state")
                        ),
                    }
                    if payload["includeContent"]:
                        rows = db.execute(
                            "SELECT payload_json FROM drafts ORDER BY id LIMIT 5001"
                        ).fetchall()
                        if (
                            len(rows) > 5000
                            or sum(len(r[0].encode("utf-8")) for r in rows) > 1024 * 1024
                        ):
                            raise ProjectError("DIAGNOSTIC_CONTENT_LIMIT", 422)
                        files["content.json"] = redact(
                            [json.loads(r[0]) for r in rows], self._secrets()
                        )
            job_id = str(uuid4())
            receipt = self.owner._receipt(operation, job_id, 0)
            receipt["state"] = "accepted"
            with connect(self.owner._application) as db, db:
                db.execute(
                    "INSERT INTO global_jobs VALUES(?,'diagnostic','running',NULL)", (job_id,)
                )
                db.execute(
                    "INSERT INTO global_operations VALUES(?,?,?,'accepted',?,?,?,?)",
                    (
                        operation,
                        digest,
                        "createDiagnostic",
                        job_id,
                        canonical(receipt),
                        "",
                        canonical(payload),
                    ),
                )
            temporary = target.parent / (".avi-diagnostic-" + job_id + ".tmp")
            try:
                checked_path(target.parent, directory=True)
                with temporary.open("xb") as stream:
                    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                        for name, value in files.items():
                            archive.writestr(name, json.dumps(value, ensure_ascii=False, indent=2))
                    stream.flush()
                    os.fsync(stream.fileno())
                checked_path(target.parent, directory=True)
                # Windows rename is exclusive and works on FAT/exFAT as well as NTFS.
                # POSIX rename overwrites, so retain link-based exclusive publication there.
                if os.name == "nt":
                    os.rename(temporary, target)
                else:
                    os.link(temporary, target)
                    temporary.unlink()
                with connect(self.owner._application) as db, db:
                    db.execute(
                        "UPDATE global_jobs SET state='succeeded',result_json=? WHERE id=?",
                        (
                            canonical(
                                {
                                    "files": list(files),
                                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                                }
                            ),
                            job_id,
                        ),
                    )
            except (OSError, zipfile.BadZipFile):
                with connect(self.owner._application) as db, db:
                    db.execute(
                        "UPDATE global_jobs SET state='failed',result_json=? WHERE id=?",
                        (
                            canonical({"errorCode": "STORAGE_UNAVAILABLE"}),
                            job_id,
                        ),
                    )
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            return receipt

    def recover(self) -> None:
        with connect(self.owner._application) as db, db:
            db.execute(
                "UPDATE global_jobs SET state='failed',result_json=? "
                "WHERE kind='diagnostic' AND state='running'",
                (canonical({"errorCode": "JOB_INTERRUPTED"}),),
            )
