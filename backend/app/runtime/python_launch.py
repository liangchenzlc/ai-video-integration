"""Launch the actual interpreter, keeping Windows venv redirectors out of PID identity."""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PythonLaunch:
    argv: list[str]
    environment: dict[str, str] = field(repr=False)


def python_launch(module: str, arguments: list[str]) -> PythonLaunch:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA"}
    }
    environment["PYTHONUTF8"] = "1"
    if getattr(sys, "frozen", False):
        return PythonLaunch([sys.executable, *arguments], environment)
    base_executable = getattr(sys, "_base_executable", None)
    if not isinstance(base_executable, str):
        raise RuntimeError("The configured base interpreter is unavailable")
    base = Path(base_executable)
    if not base.is_absolute() or not base.is_file():
        raise RuntimeError("The configured base interpreter is unavailable")
    # CPython's Windows venv redirector sets this exact variable for its child.
    # Set it from our interpreter, never inherited input. This preserves venv
    # packages while CreateProcess's PID is the PID executing Python code.
    environment["__PYVENV_LAUNCHER__"] = sys.executable
    return PythonLaunch([str(base), "-u", "-X", "utf8", "-m", module, *arguments], environment)
