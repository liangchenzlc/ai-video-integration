"""A real process that acknowledges stop but leaves itself and a descendant alive."""

import os
import subprocess
import sys
import time

from app.runtime.channel import ControlOutput, read_init
from app.runtime.control_protocol import StopFrame
from app.runtime.inbox import ControlInbox

inbox = ControlInbox(sys.stdin.fileno(), "supervisorToApi")
init = read_init(inbox, time.monotonic())
output = ControlOutput(sys.stdout.fileno(), "apiToSupervisor", init)
descendant = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(120)"],
    creationflags=subprocess.CREATE_NO_WINDOW,
)
output.emit(
    "ready",
    {
        "host": "127.0.0.1",
        "port": 1,
        "apiPid": os.getpid(),
        "apiVersion": 1,
        "backendVersion": "0.1.0",
    },
)
while True:
    event = inbox.poll()
    if isinstance(event, StopFrame):
        output.emit("stop_ack", {"forSeq": event.seq})
    time.sleep(0.01)
