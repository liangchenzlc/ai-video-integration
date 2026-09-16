"""B13 tool fixtures only: placeholder EXEs are never executed or distributed."""

import hashlib
import importlib.metadata
import importlib.util
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
UPDATE_SCRIPT = ROOT / "scripts/stage-update.ps1"


def manifest_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "fixture_release_manifest", ROOT / "scripts/release_manifest.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def put(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_fixture_manifest_hashes_versions_unverified_signing_and_actual_license_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = manifest_module()
    source, output = tmp_path / "source", tmp_path / "directory-fixture"
    electron = put(output / "AI Video Integration.exe", b"not an executable: Electron fixture")
    backend = put(
        output / "resources/backend/avi_backend.exe", b"not an executable: backend fixture"
    )
    put(source / "frontend/package.json", b'{"version":"0.1.0"}')
    lock = put(source / "frontend/pnpm-lock.yaml", b"lockfileVersion: '9.0'\n")
    put(source / "backend/uv.lock", b"version = 1\n")
    distribution = tmp_path / "site/fixture_runtime-1.2.3.dist-info"
    put(
        distribution / "METADATA",
        b"Metadata-Version: 2.3\nName: fixture-runtime\nVersion: 1.2.3\nLicense-Expression: MIT\n",
    )
    put(distribution / "LICENSE", b"PYTHON-FIXTURE-LICENSE: permission notice\n")
    put(distribution / "RECORD", b"fixture_runtime-1.2.3.dist-info/LICENSE,,\n")
    # Use real local distribution metadata, avoiding unrelated developer-environment packages.
    monkeypatch.setattr(
        module.importlib.metadata,
        "distributions",
        lambda: [importlib.metadata.PathDistribution(distribution)],
    )
    node = source / "frontend/node_modules/.pnpm/fixture-ui@2.3.4/node_modules/fixture-ui"
    put(node / "package.json", b'{"name":"fixture-ui","version":"2.3.4","license":"Apache-2.0"}')
    put(node / "LICENSE", b"NODE-FIXTURE-LICENSE: redistribution notice\n")
    manifest = module.build_manifest(source, output)
    assert manifest["appVersion"] == manifest["backendVersion"] == "0.1.0"
    assert manifest["projectSchemaVersion"] == 8
    assert manifest["environment"]["sqlite"] == sqlite3.sqlite_version
    assert manifest["signing"]["verified"] is False
    assert manifest["signing"]["status"] == "not_verified"
    by_path = {item["path"]: item for item in manifest["files"]}
    for path in (electron, backend):
        entry = by_path[path.relative_to(output).as_posix()]
        assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert entry["bytes"] == path.stat().st_size
    assert (
        next(item for item in manifest["lockfiles"] if item["path"] == "frontend/pnpm-lock.yaml")[
            "sha256"
        ]
        == hashlib.sha256(lock.read_bytes()).hexdigest()
    )
    assert {
        (entry["runtime"], entry["name"], entry["version"], entry["license"])
        for entry in manifest["dependencies"]
    } == {
        ("python", "fixture-runtime", "1.2.3", "MIT"),
        ("node", "fixture-ui", "2.3.4", "Apache-2.0"),
    }
    notices = output / "THIRD_PARTY_NOTICES.txt"
    assert "PYTHON-FIXTURE-LICENSE" in notices.read_text("utf-8")
    assert "NODE-FIXTURE-LICENSE" in notices.read_text("utf-8")
    assert by_path[notices.name]["sha256"] == hashlib.sha256(notices.read_bytes()).hexdigest()


def powershell(
    arguments: list[str], *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    shell = shutil.which("powershell.exe")
    assert shell is not None, "Windows PowerShell is needed for the rollback tool fixture"
    return subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW,
        env=env,
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows rollback script")
def test_stage_update_copies_and_verifies_placeholder_installation(tmp_path: Path) -> None:
    installed, rollback = tmp_path / "installed", tmp_path / "rollback"
    put(installed / "AI Video Integration.exe", b"fixture: never execute")
    put(installed / "resources/backend/avi_backend.exe", b"fixture backend: never execute")
    put(installed / ".fixture-marker", b"hidden-name fixture is copied too")
    result = powershell(
        [
            "-File",
            str(UPDATE_SCRIPT),
            "-InstalledDirectory",
            str(installed),
            "-RollbackDirectory",
            str(rollback),
        ]
    )
    if result.returncode and ("Get-CimInstance" in result.stderr):
        # Managed sandboxes can deny WMI. This fixture has no executable processes;
        # isolate only that read-only query and retain the actual copy/hash script.
        assert not rollback.exists(), result.stderr
        environment = dict(
            os.environ,
            AVI_UPDATE_SCRIPT=str(UPDATE_SCRIPT),
            AVI_UPDATE_SOURCE=str(installed),
            AVI_UPDATE_ROLLBACK=str(rollback),
        )
        result = powershell(
            [
                "-Command",
                "function Get-CimInstance { param([string]$ClassName) @() }; "
                "& $env:AVI_UPDATE_SCRIPT -InstalledDirectory $env:AVI_UPDATE_SOURCE "
                "-RollbackDirectory $env:AVI_UPDATE_ROLLBACK",
            ],
            env=environment,
        )
        print(
            "Rollback fixture used an empty CIM process-query stub; "
            "process detection is unverified."
        )
    else:
        print("Rollback fixture used the actual read-only CIM process query.")
    assert result.returncode == 0, result.stderr
    assert "Rollback application copy verified" in result.stdout
    source_files = {
        path.relative_to(installed): path.read_bytes()
        for path in installed.rglob("*")
        if path.is_file()
    }
    backup_files = {
        path.relative_to(rollback): path.read_bytes()
        for path in rollback.rglob("*")
        if path.is_file()
    }
    assert backup_files == source_files
    assert not (tmp_path / "application.sqlite3").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction ancestry")
def test_stage_update_rejects_junction_ancestor_back_into_installation(tmp_path: Path) -> None:
    installed, alias = tmp_path / "installed", tmp_path / "alias"
    put(installed / "AI Video Integration.exe", b"fixture: never execute")
    environment = dict(os.environ, AVI_JUNCTION_PATH=str(alias), AVI_JUNCTION_TARGET=str(installed))
    result = powershell(
        [
            "-Command",
            "$ErrorActionPreference='Stop'; New-Item -ItemType Junction "
            "-Path $env:AVI_JUNCTION_PATH -Target $env:AVI_JUNCTION_TARGET | Out-Null",
        ],
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    try:
        assert alias.is_junction()
        result = powershell(
            [
                "-File",
                str(UPDATE_SCRIPT),
                "-InstalledDirectory",
                str(installed),
                "-RollbackDirectory",
                str(alias / "backup"),
            ]
        )
        assert result.returncode != 0
        assert "must not traverse linked directories" in result.stderr
        assert not (installed / "backup").exists()
        assert (installed / "AI Video Integration.exe").read_bytes() == b"fixture: never execute"
    finally:
        # Remove only this fixture's junction, never recurse into its installation target.
        assert alias.parent.resolve() == tmp_path.resolve()
        assert alias.resolve().is_relative_to(tmp_path.resolve())
        if alias.is_junction():
            alias.rmdir()
