"""Finite local media routes and bounded-memory single-range binary responses."""

import os
import re
import stat
from collections.abc import Iterator
from pathlib import Path as FilePath
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from starlette.background import BackgroundTask
from starlette.responses import Response, StreamingResponse

from app.api.v1.media_models import (
    CancelJob,
    ConfigureTools,
    ImportMedia,
    Job,
    Media,
    MediaPage,
    RelocateMedia,
)
from app.api.v1.models import Uuid
from app.api.v1.projects import ProjectStore, project_session, window_identity
from app.api.v1.projects_models import Command, Envelope, MutationReceipt
from app.api.v1.settings_models import Settings
from app.storage.errors import ProjectError
from app.storage.paths import checked_path


def byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    if size <= 0:
        return None
    if header is None:
        return 0, size - 1
    if len(header) > 100:
        return None
    match = re.fullmatch(r"bytes=(\d{0,10})-(\d{0,10})", header)
    if not match:
        return None
    first, last = match.groups()
    if not first:
        length = int(last or "0")
        return (max(0, size - length), size - 1) if length > 0 else None
    start, end = int(first), min(int(last) if last else size - 1, size - 1)
    return (start, end) if 0 <= start <= end else None


def media_response(request: Request, source: FilePath, metadata: dict[str, Any]) -> Response:
    checked_path(source, directory=False)
    before = source.stat()
    stream = source.open("rb")
    actual = os.fstat(stream.fileno())
    if (
        not stat.S_ISREG(actual.st_mode)
        or actual.st_ino != before.st_ino
        or actual.st_dev != before.st_dev
        or actual.st_size != metadata["byteLength"]
        or not 0 < actual.st_size <= 2 * 1024**3
    ):
        stream.close()
        raise ProjectError("MEDIA_UNAVAILABLE", 409)
    values = request.headers.getlist("range")
    selected = (
        byte_range(values[0] if len(values) == 1 else None, actual.st_size)
        if len(values) <= 1
        else None
    )
    headers = {"Accept-Ranges": "bytes", "ETag": f'"{metadata["sha256"]}"'}
    if selected is None:
        stream.close()
        return Response(
            status_code=416, headers={**headers, "Content-Range": f"bytes */{actual.st_size}"}
        )
    start, end = selected
    length = end - start + 1
    headers["Content-Length"] = str(length)
    if values:
        headers["Content-Range"] = f"bytes {start}-{end}/{actual.st_size}"
    status = 206 if values else 200
    if request.method == "HEAD":
        stream.close()
        return Response(status_code=status, media_type=metadata["mime"], headers=headers)

    def chunks() -> Iterator[bytes]:
        with stream:
            stream.seek(start)
            remaining = length
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    raise OSError("Media changed during stream")
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        chunks(),
        status_code=status,
        media_type=metadata["mime"],
        headers=headers,
        background=BackgroundTask(stream.close),
    )


def media_router(store: ProjectStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["T02 media"])

    def result(request: Request, data: Any) -> dict[str, Any]:
        return {"requestId": request.state.request_id, "data": data}

    @router.get("/settings", operation_id="getSettings", response_model=Envelope[Settings])
    def settings(request: Request, window: int = Depends(window_identity)) -> dict[str, Any]:
        return result(request, store.get().get_tool_settings())

    @router.put(
        "/settings/media-tools",
        operation_id="configureMediaTools",
        response_model=Envelope[MutationReceipt],
    )
    def configure(
        request: Request, command: Command[ConfigureTools], window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request, store.get().configure_tools(command.model_dump(by_alias=True), window)
        )

    @router.post(
        "/projects/{project_id}/imports",
        operation_id="importMedia",
        status_code=202,
        response_model=Envelope[MutationReceipt],
    )
    def import_media(
        project_id: Uuid,
        request: Request,
        command: Command[ImportMedia],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().import_media(
                project_id, project_session(request), window, command.model_dump(by_alias=True)
            ),
        )

    @router.get(
        "/projects/{project_id}/media", operation_id="listMedia", response_model=Envelope[MediaPage]
    )
    def list_media(
        project_id: Uuid,
        request: Request,
        cursor: Uuid | None = None,
        limit: int = Query(50, ge=1, le=200),
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().list_media(
                project_id, project_session(request), window, cursor=cursor, limit=limit
            ),
        )

    @router.get(
        "/projects/{project_id}/media/{media_id}/metadata",
        operation_id="getMediaMetadata",
        response_model=Envelope[Media],
    )
    def metadata(
        project_id: Uuid, media_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request, store.get().get_media(project_id, project_session(request), window, media_id)
        )

    @router.get(
        "/projects/{project_id}/media/{media_id}",
        operation_id="getMediaBytes",
        response_class=Response,
    )
    @router.head(
        "/projects/{project_id}/media/{media_id}",
        operation_id="headMediaBytes",
        response_class=Response,
    )
    def binary(
        project_id: Uuid, media_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> Response:
        service = store.get()
        session = project_session(request)
        metadata = service.get_media(project_id, session, window, media_id)
        path = service.media_file(project_id, session, window, media_id)
        return media_response(request, path, metadata)

    @router.post(
        "/projects/{project_id}/media/{media_id}/relocate",
        operation_id="relocateMedia",
        status_code=202,
        response_model=Envelope[MutationReceipt],
    )
    def relocate(
        project_id: Uuid,
        media_id: Uuid,
        request: Request,
        command: Command[RelocateMedia],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().relocate_media(
                project_id,
                project_session(request),
                window,
                media_id,
                command.model_dump(by_alias=True),
            ),
        )

    @router.get(
        "/projects/{project_id}/jobs",
        operation_id="listLocalJobs",
        response_model=Envelope[list[Job]],
    )
    def jobs(
        project_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(request, store.get().list_jobs(project_id, project_session(request), window))

    @router.get(
        "/projects/{project_id}/jobs/{job_id}",
        operation_id="getLocalJob",
        response_model=Envelope[Job],
    )
    def job(
        project_id: Uuid, job_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request, store.get().get_job(project_id, project_session(request), window, job_id)
        )

    @router.post(
        "/projects/{project_id}/jobs/{job_id}/cancel",
        operation_id="cancelLocalJob",
        response_model=Envelope[MutationReceipt],
    )
    def cancel(
        project_id: Uuid,
        job_id: Uuid,
        request: Request,
        command: Command[CancelJob],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().cancel_job(
                project_id,
                project_session(request),
                window,
                job_id,
                command.model_dump(by_alias=True),
            ),
        )

    return router
