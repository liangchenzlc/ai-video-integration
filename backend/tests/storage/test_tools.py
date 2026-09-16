import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from app.storage import tools


def test_subprocess_output_and_time_are_bounded(monkeypatch: Any) -> None:
    monkeypatch.setattr(tools, "OUTPUT_LIMIT", 128)
    with pytest.raises(Exception, match="MEDIA_TOOL_OUTPUT_LIMIT"):
        tools.run([sys.executable, "-c", "print('x' * 10000)"])
    monkeypatch.setattr(tools, "TIMEOUT", 0.05)
    with pytest.raises(Exception, match="MEDIA_PROBE_TIMEOUT"):
        tools.run([sys.executable, "-c", "import time;time.sleep(10)"])


def test_subprocess_cancel_and_missing_tool_are_fixed_errors(tmp_path: Path) -> None:
    stop = threading.Event()
    stop.set()
    with pytest.raises(Exception, match="JOB_INTERRUPTED"):
        tools.run([sys.executable, "-c", "import time;time.sleep(10)"], stop)
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"not executable")
    with pytest.raises(Exception, match="MEDIA_TOOLS_UNAVAILABLE"):
        tools.inspect_tools(ffmpeg)
