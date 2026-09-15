import sys

import pytest
from app.runtime.python_launch import python_launch


def test_child_environment_is_allowlisted_and_launcher_is_computed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "TEST_ONLY_SECRET_SENTINEL"
    for name in (
        "SERVICE_API_KEY",
        "PYTHONPATH",
        "PYTHONHOME",
        "NODE_OPTIONS",
        "__PYVENV_LAUNCHER__",
    ):
        monkeypatch.setenv(name, sentinel)
    launch = python_launch("probes.entrypoint", ["--role=api"])
    assert launch.environment["__PYVENV_LAUNCHER__"] == sys.executable
    assert sentinel not in repr(launch)
    assert sentinel not in str(launch.environment)
    assert launch.argv[0] == sys._base_executable
    assert launch.environment["PYTHONUTF8"] == "1"


def test_missing_actual_interpreter_fails_without_path_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "_base_executable", r"Z:\missing\python.exe")
    with pytest.raises(RuntimeError, match="unavailable"):
        python_launch("probes.entrypoint", ["--role=api"])
