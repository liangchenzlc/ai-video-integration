"""Summarize existing passing reports and hash the T01 delivery inputs."""

import hashlib
import json
import platform
import sqlite3
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    backend = ET.parse(ROOT / ".cache/t01-c-backend-tests.xml").getroot()[0].attrib
    frontend = json.loads((ROOT / ".cache/t01-frontend-tests.json").read_text(encoding="utf-8"))
    desktop = json.loads(
        (ROOT / "docs/开发记录/t01-packaged-tests.json").read_text(encoding="utf-8")
    )
    if any(int(backend[k]) for k in ("errors", "failures", "skipped")):
        raise RuntimeError("Backend report is not fully passing")
    if not frontend["success"] or frontend["numPendingTests"]:
        raise RuntimeError("Frontend report is not fully passing")
    if any(desktop["stats"][k] for k in ("unexpected", "flaky", "skipped")):
        raise RuntimeError("Packaged report is not fully passing")
    files = []
    for base in ("backend/app", "frontend/electron", "frontend/src", "contracts"):
        files.extend(
            p for p in (ROOT / base).rglob("*") if p.is_file() and "__pycache__" not in p.parts
        )
    for base in ("frontend", "backend", "scripts"):
        files.extend(p for p in (ROOT / base).iterdir() if p.is_file())
    hashes = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(set(files))
    }
    package = ROOT / "release/t01/win-unpacked"
    metrics = json.loads(
        (ROOT / "docs/开发记录/t01-packaged-metrics.json").read_text(encoding="utf-8")
    )
    report = {
        "recordedAt": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "python": sys.version.split()[0],
        "sqliteRuntime": sqlite3.sqlite_version,
        "backend": {"passed": int(backend["tests"]), "seconds": float(backend["time"])},
        "frontend": {"passed": frontend["numPassedTests"]},
        "packagedDesktop": desktop["stats"],
        "metrics": metrics,
        "packageBytes": sum(p.stat().st_size for p in package.rglob("*") if p.is_file()),
        "package": package.relative_to(ROOT).as_posix(),
        "artifactSha256": {
            str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (
                package / "AI Video Integration.exe",
                package / "resources/app.asar",
                package / "resources/backend/avi_backend.exe",
            )
        },
        "sourceSha256": hashes,
        "review": "implementation self-review; no independent reviewer",
        "scope": "T01 engineering acceptance only; T02-T14 not implemented",
    }
    (ROOT / "docs/开发记录/t01-final-evidence.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "sourceSha256"}, indent=2))


if __name__ == "__main__":
    main()
