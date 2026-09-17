"""Generate an inventory from an actual local directory build, without signing claims."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def build_manifest(root: Path, output: Path) -> dict[str, object]:
    output = output.resolve(strict=True)
    executable = output / "AI Video Integration.exe"
    backend = output / "resources/backend/avi_backend.exe"
    if not executable.is_file() or not backend.is_file():
        raise ValueError("Expected the complete Electron and Python directory package")
    dependencies: list[dict[str, str]] = []
    notices: list[str] = [
        (
            "Third-party dependency inventory from this build.\n"
            "License metadata is declared by each package; distribution review remains required.\n"
        )
    ]
    for distribution in sorted(
        importlib.metadata.distributions(),
        key=lambda d: d.metadata.get("Name", "").lower(),
    ):
        name = distribution.metadata.get("Name", "unknown")
        license_text = distribution.metadata.get(
            "License-Expression"
        ) or distribution.metadata.get("License", "unspecified")
        dependencies.append(
            {
                "runtime": "python",
                "name": name,
                "version": distribution.version,
                "license": license_text,
            }
        )
        notices.append(
            f"\nPython: {name} {distribution.version}\nDeclared license: {license_text}\n"
        )
        for item in distribution.files or []:
            if any(
                term in item.name.lower() for term in ("license", "copying", "notice")
            ):
                path = Path(distribution.locate_file(item))
                if path.is_file() and path.stat().st_size < 256 * 1024:
                    notices.append(path.read_text("utf-8", errors="replace"))
    node_root = root / "frontend/node_modules/.pnpm"
    seen: set[tuple[str, str]] = set()
    for package in sorted(node_root.glob("*/node_modules/**/package.json")):
        try:
            metadata = json.loads(package.read_text("utf-8"))
        except (ValueError, OSError):
            continue
        name, version = metadata.get("name"), metadata.get("version")
        if (
            not isinstance(name, str)
            or not isinstance(version, str)
            or (name, version) in seen
        ):
            continue
        seen.add((name, version))
        declared = str(metadata.get("license", "unspecified"))
        dependencies.append(
            {"runtime": "node", "name": name, "version": version, "license": declared}
        )
        notices.append(f"\nNode: {name} {version}\nDeclared license: {declared}\n")
        for path in package.parent.iterdir():
            if (
                path.is_file()
                and path.name.lower().startswith(("license", "copying", "notice"))
                and path.stat().st_size < 256 * 1024
            ):
                notices.append(path.read_text("utf-8", errors="replace"))
    (output / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(notices), "utf-8")
    files = [
        {
            "path": str(path.relative_to(output)).replace("\\", "/"),
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        }
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "release-manifest.json"
    ]
    locks = [root / "frontend/pnpm-lock.yaml", root / "backend/uv.lock"]
    package_json = json.loads((root / "frontend/package.json").read_text("utf-8"))
    return {
        "manifestVersion": 1,
        "createdAt": datetime.now(UTC).isoformat(),
        "appVersion": package_json["version"],
        "backendVersion": package_json["version"],
        "apiVersion": "1.0.0",
        "controlVersion": 1,
        "projectSchemaVersion": 8,
        "environment": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
        },
        "lockfiles": [
            {"path": str(p.relative_to(root)).replace("\\", "/"), "sha256": digest(p)}
            for p in locks
            if p.is_file()
        ],
        "files": files,
        "dependencies": dependencies,
        "signing": {
            "verified": False,
            "status": "not_verified",
            "reason": (
                "No publisher certificate or independent signature verification "
                "is asserted by this inventory."
            ),
        },
        "ffmpeg": {"bundled": False, "source": "User-selected local compatible build"},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = build_manifest(root, args.directory)
    (args.directory / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8"
    )
    print(
        "Local release inventory written; signing and clean-system validation remain separate."
    )


if __name__ == "__main__":
    main()
