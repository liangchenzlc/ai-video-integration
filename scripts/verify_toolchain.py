"""Verify installed direct versions against the design baseline, without network."""

import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    baseline = json.loads(
        (ROOT / "docs/技术方案/契约/t01-toolchain-baseline.json").read_text(encoding="utf-8")
    )
    actual = {"python": platform.python_version()}
    node = ROOT / ".tools/node/node.exe"
    commands = {
        "node": [str(node), "--version"],
        "pnpm": [str(node), str(ROOT / ".tools/pnpm/bin/pnpm.cjs"), "--version"],
        "uv": [str(ROOT / ".tools/uv/uv.exe"), "--version"],
    }
    for name, argv in commands.items():
        result = subprocess.run(
            argv,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=15,
        ).stdout.strip()
        actual[name] = result.split()[1] if name == "uv" else result.removeprefix("v")
    for name in baseline["backend"] | baseline["backendDev"]:
        actual[name] = importlib.metadata.version(name)
    for name in baseline["frontend"]:
        metadata = json.loads(
            (ROOT / "frontend/node_modules" / name / "package.json").read_text(encoding="utf-8")
        )
        actual[name] = metadata["version"]
    expected = {
        "node": baseline["target"]["node"],
        "python": baseline["target"]["python"],
        **baseline["tools"],
        **baseline["frontend"],
        **baseline["backend"],
        **baseline["backendDev"],
    }
    differences = {
        name: {"expected": value, "actual": actual.get(name)}
        for name, value in expected.items()
        if actual.get(name) != value
    }
    report = {
        "checkedAt": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "pythonExecutable": sys.executable,
        "versions": actual,
        "differences": differences,
        "passed": not differences,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
