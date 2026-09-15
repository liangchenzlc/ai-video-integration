"""Authentication and bounded request checks run before every HTTP route."""

import asyncio
import base64
import hmac
import re
import time
from uuid import uuid4

from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import error_response
from app.api.v1.models import UUID_PATTERN, ErrorCode
from app.runtime.context import RuntimeContext

HTTP_LIMIT = 64 * 1024


class RuntimeSecurity:
    def __init__(self, app: ASGIApp, context: RuntimeContext) -> None:
        self.app = app
        self.context = context
        self._authorization = b"Bearer " + base64.urlsafe_b64encode(context.token_bytes).rstrip(
            b"="
        )
        self._host = f"127.0.0.1:{context.port}".encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        started = complete = False
        response_size = 0

        async def guarded_send(message: Message) -> None:
            nonlocal started, complete, response_size
            if message["type"] == "http.response.start":
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower()
                    not in {b"x-request-id", b"cache-control", b"x-content-type-options"}
                ]
                headers += [
                    (b"x-request-id", request_id.encode("ascii")),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ]
                message = {**message, "headers": headers}
                started = True
            elif message["type"] == "http.response.body":
                response_size += len(message.get("body", b""))
                if response_size > HTTP_LIMIT:
                    raise ValueError("Runtime response exceeds limit")
                complete = not message.get("more_body", False)
            await send(message)

        async def reject(code: ErrorCode, status: int | None = None) -> None:
            await error_response(code, request_id, status)(scope, receive, guarded_send)

        try:
            headers: dict[bytes, list[bytes]] = {}
            for key, value in scope["headers"]:
                headers.setdefault(key.lower(), []).append(value)
            if (
                len(headers.get(b"authorization", [])) > 1
                or len(headers.get(b"content-length", [])) > 1
            ):
                await reject("REQUEST_INVALID", 400)
                return
            if headers.get(b"host") != [self._host]:
                await reject("HOST_REJECTED")
                return
            if b"origin" in headers:
                await reject("ORIGIN_REJECTED")
                return
            authorization = headers.get(b"authorization", [])
            if not authorization:
                await reject("AUTH_REQUIRED")
                return
            if len(authorization[0]) > 128 or not hmac.compare_digest(
                authorization[0], self._authorization
            ):
                await reject("AUTH_INVALID")
                return
            ids = headers.get(b"x-request-id", [])
            if ids:
                if len(ids) != 1 or re.fullmatch(UUID_PATTERN.encode("ascii"), ids[0]) is None:
                    await reject("REQUEST_INVALID")
                    return
                request_id = ids[0].decode("ascii")
            scope.setdefault("state", {})["request_id"] = request_id
            if scope.get("query_string", b""):
                await reject("REQUEST_INVALID")
                return
            length_header = headers.get(b"content-length", [])
            if length_header and (
                len(length_header[0]) > 20
                or not length_header[0].isdigit()
                or b"transfer-encoding" in headers
            ):
                await reject("REQUEST_INVALID", 400)
                return
            if length_header and int(length_header[0]) > HTTP_LIMIT:
                await Response(status_code=413, headers={"Connection": "close"})(
                    scope, receive, guarded_send
                )
                return
            size = 0
            deadline = time.monotonic() + 1.5
            while True:
                try:
                    message = await asyncio.wait_for(receive(), max(0, deadline - time.monotonic()))
                except TimeoutError:
                    await reject("REQUEST_INVALID", 400)
                    return
                if message["type"] == "http.disconnect":
                    return
                if message["type"] != "http.request":
                    await reject("REQUEST_INVALID", 400)
                    return
                size += len(message.get("body", b""))
                if size > HTTP_LIMIT:
                    await Response(status_code=413, headers={"Connection": "close"})(
                        scope, receive, guarded_send
                    )
                    return
                if not message.get("more_body", False):
                    break
            if size or (length_header and int(length_header[0]) != size):
                await reject("REQUEST_INVALID", 400)
                return

            async def empty_receive() -> Message:
                return {"type": "http.request", "body": b"", "more_body": False}

            await self.app(scope, empty_receive, guarded_send)
        except Exception:
            # Suppress raw exception logging by handling errors inside Starlette's
            # outer ServerErrorMiddleware. Never inspect or stringify the exception.
            if not started:
                await error_response("INTERNAL_ERROR", request_id)(scope, receive, guarded_send)
            elif not complete:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
