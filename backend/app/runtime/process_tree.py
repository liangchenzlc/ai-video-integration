"""Bounded teardown of one owned process tree, independent of wire protocol."""

import time
from dataclasses import dataclass

from app.runtime.windows_job import ManagedProcess, WindowsJob


@dataclass(frozen=True)
class StopResult:
    forced: bool
    active_processes: int


def finish_tree(job: WindowsJob, child: ManagedProcess, grace_ms: int = 5000) -> StopResult:
    """Call after sending stop/EOF. Never report success before the Job is empty."""
    if not 0 <= grace_ms <= 5000:
        raise ValueError("Shutdown grace must be between zero and five seconds")
    deadline = time.monotonic() + grace_ms / 1000 + 2
    # Wait for the whole Job, including console hosts and possible descendants.
    # Waiting only for the root can misreport success while media children live.
    forced = not job.wait_empty(grace_ms)
    if forced:
        job.terminate_job()
    if not job.wait_empty(max(0, int((deadline - time.monotonic()) * 1000))):
        raise TimeoutError("Owned process tree did not exit")
    child.wait(max(0, int((deadline - time.monotonic()) * 1000)))
    return StopResult(forced, 0)
