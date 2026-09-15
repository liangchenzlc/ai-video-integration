"""Run the Electron directory fixture in a Chinese/space path without Python PATH."""

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.runtime.windows_job import WindowsJob  # noqa: E402


def main() -> None:
    source = ROOT / "release/t01-a/win-unpacked"
    destination = ROOT / ".cache/桌面 中文测试/AI Video Probe"
    if not (source / "AI Video Probe.exe").is_file():
        raise RuntimeError("Build the Electron probe directory package first")
    shutil.copytree(source, destination, dirs_exist_ok=True)
    result_path = destination / "probe-result.json"
    result_path.unlink(missing_ok=True)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
        }
    }
    environment["PATH"] = environment.get("SystemRoot", r"C:\Windows") + r"\System32"
    with WindowsJob() as job:
        child = job.spawn_suspended_in_job(
            [str(destination / "AI Video Probe.exe")],
            cwd=str(destination),
            env=environment,
        )
        try:
            try:
                exit_code = child.wait(25000)
            except TimeoutError:
                job.terminate_job()
                if not job.wait_empty(2000):
                    raise RuntimeError("Timed-out desktop probe did not terminate") from None
                child.wait(2000)
                raise RuntimeError(
                    "Desktop probe timed out: "
                    + child.stderr.read(1000).decode("utf-8", errors="replace")
                ) from None
            if not job.wait_empty(2000):
                raise RuntimeError("Desktop probe left owned descendants")
            stderr = child.stderr.read(1000)
        finally:
            job.close()
            child.close()
    if not result_path.is_file():
        raise RuntimeError(
            f"Probe exited {exit_code} without a report: "
            + stderr.decode("utf-8", errors="replace")
        )
    report = json.loads(result_path.read_text(encoding="utf-8"))
    report["desktopExitCode"] = exit_code
    required = {
        "passed": True,
        "packaged": True,
        "rendererLoaded": True,
        "streams": True,
        "stopped": True,
        "activeJobProcesses": 0,
        "backendExitCode": 0,
        "desktopExitCode": 0,
        "electron": "44.3.0",
    }
    for key, expected in required.items():
        if report.get(key) != expected:
            raise RuntimeError(f"Probe assertion failed for {key}: {report}")
    evidence = ROOT / "docs/开发记录/t01-a-desktop-probe.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
