"""Authentication and bounded request checks run before every HTTP route."""

import asyncio
import base64
import hmac
import json
import re
import time
from urllib.parse import parse_qsl
from uuid import uuid4

from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import error_response
from app.api.v1.models import UUID_PATTERN, ErrorCode
from app.runtime.context import RuntimeContext

HTTP_LIMIT = 64 * 1024
BUSINESS_LIMIT = 1024 * 1024
# Extend only as corresponding routes are implemented. Unknown paths keep runtime rules.
BUSINESS_WRITES = {
    ("POST", "/api/v1/file-grants"),
    ("POST", "/api/v1/projects"),
    ("POST", "/api/v1/project-sessions"),
    ("PUT", "/api/v1/settings/media-tools"),
    ("PUT", "/api/v1/settings/storage"),
    ("POST", "/api/v1/connection-checks"),
}
_PATH_UUID = UUID_PATTERN.removeprefix("^").removesuffix("$")
DRAFT_PATH = re.compile(rf"/api/v1/projects/{_PATH_UUID}/drafts/{_PATH_UUID}")
MEDIA_PATH = re.compile(rf"/api/v1/projects/{_PATH_UUID}/media/{_PATH_UUID}")
MEDIA_LIST_PATH = re.compile(rf"/api/v1/projects/{_PATH_UUID}/media")
MEDIA_WRITE_PATH = re.compile(
    rf"/api/v1/projects/{_PATH_UUID}/(?:imports|media/{_PATH_UUID}/relocate|jobs/{_PATH_UUID}/cancel)"
)
STAGE_MODELS_PATH = re.compile(rf"/api/v1/projects/{_PATH_UUID}/stage-models")
# Match the credential route before payload validation, including invalid provider
# segments, so malformed secrets receive a static validation error without echoes.
CREDENTIAL_PATH = re.compile(r"/api/v1/credentials/[^/]+")
CREDENTIAL_DELETE_PATH = re.compile(r"/api/v1/credentials/[^/]+/delete")
TASK_LIST_PATH = re.compile(rf"/api/v1/projects/{_PATH_UUID}/(?:tasks|cost-entries)")
TASK_READ_PATH = re.compile(
    rf"/api/v1/projects/{_PATH_UUID}/(?:budget|cost-summary|task-plans/{_PATH_UUID}|tasks(?:/{_PATH_UUID})?|calls/{_PATH_UUID}|cost-entries)"
)
TASK_POST_PATH = re.compile(
    rf"/api/v1/projects/{_PATH_UUID}/(?:task-plans|tasks|tasks/{_PATH_UUID}/continue|calls/{_PATH_UUID}/(?:recovery|settlements))"
)
TASK_PUT_PATH = re.compile(
    rf"/api/v1/projects/{_PATH_UUID}/(?:budget|external-expenses/{_PATH_UUID})"
)
REVISION_LIST_PATH = re.compile(rf"/api/v1/projects/{_PATH_UUID}/artifacts/{_PATH_UUID}/revisions")
VERSION_READ_PATH = re.compile(
    rf"/api/v1/projects/{_PATH_UUID}/(?:artifacts/{_PATH_UUID}(?:/revisions)?|check-reports/{_PATH_UUID})"
)
VERSION_POST_PATH = re.compile(
    rf"/api/v1/projects/{_PATH_UUID}/(?:artifacts/{_PATH_UUID}/(?:revisions|adoption-preview|adoptions|confirmations)|adoptions/{_PATH_UUID}/undo|local-checks)"
)


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def reject_constant(_: str) -> object:
    raise ValueError("Non-finite JSON value")


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
        draft_path = DRAFT_PATH.fullmatch(scope.get("path", "")) is not None
        business_write = (
            (scope.get("method"), scope.get("path")) in BUSINESS_WRITES
            or (
                scope.get("method") == "POST"
                and VERSION_POST_PATH.fullmatch(scope.get("path", "")) is not None
            )
            or (
                scope.get("method") == "POST"
                and TASK_POST_PATH.fullmatch(scope.get("path", "")) is not None
            )
            or (
                scope.get("method") == "PUT"
                and TASK_PUT_PATH.fullmatch(scope.get("path", "")) is not None
            )
            or (scope.get("method") == "PUT" and draft_path)
            or (
                scope.get("method") == "PUT"
                and (
                    CREDENTIAL_PATH.fullmatch(scope.get("path", "")) is not None
                    or STAGE_MODELS_PATH.fullmatch(scope.get("path", "")) is not None
                )
            )
            or (
                scope.get("method") == "POST"
                and CREDENTIAL_DELETE_PATH.fullmatch(scope.get("path", "")) is not None
            )
            or (
                scope.get("method") == "POST"
                and MEDIA_WRITE_PATH.fullmatch(scope.get("path", "")) is not None
            )
        )
        limit = BUSINESS_LIMIT if business_write else HTTP_LIMIT
        response_limit = (
            BUSINESS_LIMIT
            if business_write or (draft_path and scope.get("method") == "GET")
            else HTTP_LIMIT
        )
        if MEDIA_PATH.fullmatch(scope.get("path", "")) and scope.get("method") in {"GET", "HEAD"}:
            response_limit = 2 * 1024**3
        elif MEDIA_LIST_PATH.fullmatch(scope.get("path", "")) and scope.get("method") == "GET":
            response_limit = BUSINESS_LIMIT
        elif scope.get("path") in {"/api/v1/settings", "/api/v1/settings/details"}:
            response_limit = BUSINESS_LIMIT
        elif (
            TASK_READ_PATH.fullmatch(scope.get("path", ""))
            or VERSION_READ_PATH.fullmatch(scope.get("path", ""))
            or scope.get("path") == "/api/v1/task-activity"
        ):
            response_limit = BUSINESS_LIMIT

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
                if response_size > response_limit:
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
            query = scope.get("query_string", b"")
            if query:
                try:
                    pairs = parse_qsl(
                        query.decode("ascii"),
                        strict_parsing=True,
                        keep_blank_values=True,
                        max_num_fields=2,
                    )
                    valid_query = (
                        scope.get("method") == "GET"
                        and (
                            MEDIA_LIST_PATH.fullmatch(scope.get("path", "")) is not None
                            or TASK_LIST_PATH.fullmatch(scope.get("path", "")) is not None
                            or REVISION_LIST_PATH.fullmatch(scope.get("path", "")) is not None
                        )
                        and len(query) <= 100
                        and len({key for key, _ in pairs}) == len(pairs)
                        and all(
                            (key == "cursor" and re.fullmatch(UUID_PATTERN, value))
                            or (
                                key == "limit"
                                and re.fullmatch(r"[0-9]{1,3}", value)
                                and 1 <= int(value) <= 200
                            )
                            for key, value in pairs
                        )
                    )
                except (ValueError, UnicodeError):
                    valid_query = False
                if not valid_query:
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
            if length_header and int(length_header[0]) > limit:
                await Response(status_code=413, headers={"Connection": "close"})(
                    scope, receive, guarded_send
                )
                return
            size = 0
            chunks: list[bytes] = []
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
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > limit:
                    await Response(status_code=413, headers={"Connection": "close"})(
                        scope, receive, guarded_send
                    )
                    return
                if business_write:
                    chunks.append(chunk)
                if not message.get("more_body", False):
                    break
            if (size and not business_write) or (length_header and int(length_header[0]) != size):
                await reject("REQUEST_INVALID", 400)
                return
            body = b"".join(chunks)
            if business_write:
                if headers.get(b"content-type") not in (
                    [b"application/json"],
                    [b"application/json; charset=utf-8"],
                ):
                    await reject("REQUEST_INVALID", 400)
                    return
                try:
                    value = json.loads(
                        body.decode("utf-8", errors="strict"),
                        object_pairs_hook=unique_object,
                        parse_constant=reject_constant,
                    )
                    if not isinstance(value, dict):
                        raise ValueError("JSON object required")
                    # Validate escaped surrogate characters as well as the wire encoding.
                    json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
                except (ValueError, UnicodeError, RecursionError):
                    await reject("REQUEST_INVALID", 400)
                    return

            replayed = False

            async def empty_receive() -> Message:
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                # StreamingResponse waits on disconnect after reading the request.
                # Repeating an empty body spins forever and starves the stream.
                return await receive()

            await self.app(scope, empty_receive, guarded_send)
        except Exception:
            # Suppress raw exception logging by handling errors inside Starlette's
            # outer ServerErrorMiddleware. Never inspect or stringify the exception.
            if not started:
                await error_response("INTERNAL_ERROR", request_id)(scope, receive, guarded_send)
            elif not complete:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
