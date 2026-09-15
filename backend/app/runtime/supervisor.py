"""The sole owner of API/media processes. Never opens HTTP or business data."""

import os
import sys
import time
from pathlib import Path

from app.runtime.channel import ControlOutput, read_init
from app.runtime.control_protocol import (
    ControlErrorCode,
    ErrorFrame,
    InitFrame,
    ProtocolError,
    ReadyFrame,
    StopAckFrame,
    StopFrame,
    StopReason,
)
from app.runtime.inbox import ControlInbox, DiagnosticDrain
from app.runtime.python_launch import python_launch
from app.runtime.windows_job import ManagedProcess, WindowsJob


def supervise(init: InitFrame, parent: ControlInbox, output: ControlOutput, started: float) -> int:
    try:
        job = WindowsJob()
    except Exception:
        output.error("JOB_SETUP_FAILED")
        return 1
    child: ManagedProcess | None = None
    child_output: ControlOutput | None = None
    try:
        launch = python_launch("app.entrypoint", ["--role=api"])
        cwd = (
            str(Path(sys.executable).parent)
            if getattr(sys, "frozen", False)
            else str(Path(__file__).resolve().parents[2])
        )
        try:
            child = job.spawn_suspended_in_job(launch.argv, cwd=cwd, env=launch.environment)
        except Exception:
            output.error("API_SPAWN_FAILED")
            return 1
        incoming = ControlInbox(
            child.stdout.fileno(), "apiToSupervisor", init.runtime_id, init.generation
        )
        diagnostics = DiagnosticDrain(child.stderr.fileno())
        child_output = ControlOutput(child.stdin.fileno(), "supervisorToApi", init)
        output.emit("booted", {"supervisorPid": os.getpid(), "apiPid": child.pid})
        child_output.emit("init", init.payload.model_dump(by_alias=True))
        ready = forced = parent_lost = False
        reason: StopReason | None = None
        grace_deadline: float | None = None
        final_deadline: float | None = None
        failure: ControlErrorCode | None = None
        while True:
            now = time.monotonic()
            output.writer.check()
            if not reason and not failure:
                child_output.writer.check()
            # Parent EOF takes priority over graceful work already in flight.
            if parent.invalid:
                raise ProtocolError()
            if parent.disconnected and not parent_lost:
                parent_lost = True
                job.terminate_job()
                forced = True
                final_deadline = min(final_deadline, now + 2) if final_deadline else now + 2
            if not parent_lost:
                event = parent.poll()
                if isinstance(event, StopFrame):
                    if reason is not None:
                        raise ProtocolError()
                    reason = event.payload.reason
                    output.emit("stop_ack", {"forSeq": event.seq})
                    child_output.emit("stop", {"reason": reason})
                    grace_deadline, final_deadline = now + 5, now + 7
                elif event is not None:
                    raise ProtocolError()
            event = incoming.poll()
            if isinstance(event, ReadyFrame):
                if ready or event.payload.api_pid != child.pid:
                    raise ProtocolError()
                ready = True
                if reason is None and not parent_lost:
                    output.emit("ready", event.payload.model_dump(by_alias=True))
            elif isinstance(event, ErrorFrame):
                failure = event.payload.code
            elif isinstance(event, StopAckFrame):
                if reason is None or event.payload.for_seq != 2:
                    raise ProtocolError()
            elif event == "invalid":
                failure = "PROTOCOL_INVALID"
            elif event == "eof" and not reason and not parent_lost:
                failure = failure or "API_EXITED"
            if diagnostics.overflowed.is_set():
                failure = "PROTOCOL_INVALID"
            if child.poll() is not None and not reason and not parent_lost:
                failure = failure or "API_EXITED"
            if not ready and not reason and not parent_lost and now >= started + 30:
                failure = "START_TIMEOUT"
            if failure and not forced:
                job.terminate_job()
                forced = True
                final_deadline = now + 2
            if reason and grace_deadline is not None and now >= grace_deadline and not forced:
                if job.active_processes():
                    job.terminate_job()
                    forced = True
            if final_deadline is not None:
                if job.active_processes() == 0 and child.poll() is not None:
                    if parent_lost:
                        return 1
                    if failure:
                        output.error(failure)
                        return 1
                    output.emit(
                        "stopped", {"reason": reason, "forced": forced, "activeJobProcesses": 0}
                    )
                    return 0
                if now >= final_deadline:
                    output.error("STOP_TIMEOUT")
                    return 1
            time.sleep(0.01)
    except ProtocolError:
        job.terminate_job()
        if job.wait_empty(2000):
            output.error("PROTOCOL_INVALID")
        else:
            output.error("STOP_TIMEOUT")
        return 1
    except Exception:
        job.terminate_job()
        job.wait_empty(2000)
        output.error("INTERNAL_ERROR")
        return 1
    finally:
        job.close()
        if child_output:
            child_output.writer.close()
        if child:
            child.close()


def run_supervisor() -> int:
    started = time.monotonic()
    inbox = ControlInbox(sys.stdin.fileno(), "mainToSupervisor")
    init = read_init(inbox, started)
    output = ControlOutput(sys.stdout.fileno(), "supervisorToMain", init)
    try:
        return supervise(init, inbox, output, started)
    finally:
        try:
            output.writer.drain()
        finally:
            output.writer.close()
