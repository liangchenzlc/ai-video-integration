"""Abrupt exits at generated-image filesystem boundaries; never used in production."""

import os
import sys
import threading
from pathlib import Path

from app.services import generated_media
from tests.storage.test_media import FFMPEG

directory, call_id, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
publish = generated_media._publish


def crash(staging: Path, target: Path) -> None:
    if mode == "renamed":
        publish(staging, target)
    os._exit(51 if mode == "verified" else 52)


generated_media._publish = crash
generated_media.publish_image(directory, call_id, 0, FFMPEG, threading.Event(), synthetic=True)
