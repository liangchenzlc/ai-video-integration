"""One bound loopback socket, one API worker, one main-thread per-user mutex."""

import asyncio
import base64
import os
import socket
import sys
import time

import uvicorn

from app import __version__
from app.main import create_app
from app.runtime.api_mutex import ApiMutex, BackendAlreadyRunning
from app.runtime.channel import ControlOutput, read_init
from app.runtime.context import RuntimeContext
from app.runtime.control_protocol import InitFrame, ProtocolError, StopFrame
from app.runtime.inbox import ControlInbox


async def serve(init: InitFrame, inbox: ControlInbox, output: ControlOutput) -> int:
    from pathlib import Path

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bound:
        try:
            bound.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            bound.bind(("127.0.0.1", 0))
            bound.listen(128)
            bound.setblocking(False)
        except OSError:
            output.error("BIND_FAILED")
            return 1
        context = RuntimeContext(
            runtime_id=init.runtime_id,
            generation=init.generation,
            token_bytes=base64.urlsafe_b64decode(init.payload.token_b64_url + "="),
            app_data_dir=Path(init.payload.app_data_dir),
            mode=init.payload.mode,
            port=bound.getsockname()[1],
        )
        config = uvicorn.Config(
            create_app(context),
            host="127.0.0.1",
            port=context.port,
            workers=1,
            reload=False,
            loop="asyncio",
            http="h11",
            ws="none",
            lifespan="on",
            proxy_headers=False,
            access_log=False,
            timeout_graceful_shutdown=4,
            log_config={
                "version": 1,
                "disable_existing_loggers": False,
                "handlers": {"discard": {"class": "logging.NullHandler"}},
                "loggers": {"uvicorn": {"handlers": ["discard"], "propagate": False}},
            },
        )
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve(sockets=[bound]))
        sent_ready = stopping = False
        exit_code = 0
        try:
            while not server_task.done():
                output.writer.check()
                event = inbox.poll()
                if isinstance(event, StopFrame):
                    if stopping:
                        raise ProtocolError()
                    context.ready = False
                    stopping = True
                    server.should_exit = True
                    output.emit("stop_ack", {"forSeq": event.seq})
                elif event in ("eof", "invalid"):
                    context.ready = False
                    stopping = True
                    server.should_exit = True
                    exit_code = 1
                elif event is not None:
                    raise ProtocolError()
                if server.started and not sent_ready and not stopping:
                    context.ready = True
                    output.emit(
                        "ready",
                        {
                            "host": "127.0.0.1",
                            "port": context.port,
                            "apiPid": os.getpid(),
                            "apiVersion": 1,
                            "backendVersion": __version__,
                        },
                    )
                    sent_ready = True
                await asyncio.sleep(0.01)
            await server_task
            return exit_code if sent_ready or stopping else 1
        finally:
            context.ready = False
            server.should_exit = True
            if not server_task.done():
                try:
                    await asyncio.wait_for(server_task, timeout=4)
                except (TimeoutError, asyncio.CancelledError):
                    server_task.cancel()


def run_api() -> int:
    started = time.monotonic()
    inbox = ControlInbox(sys.stdin.fileno(), "supervisorToApi")
    init = read_init(inbox, started)
    output = ControlOutput(sys.stdout.fileno(), "apiToSupervisor", init)
    try:
        try:
            with ApiMutex():
                return asyncio.run(serve(init, inbox, output))
        except BackendAlreadyRunning:
            output.error("BACKEND_ALREADY_RUNNING")
            return 1
        except ProtocolError:
            output.error("PROTOCOL_INVALID")
            return 1
        except Exception:
            output.error("INTERNAL_ERROR")
            return 1
    finally:
        try:
            output.writer.drain()
        finally:
            output.writer.close()
