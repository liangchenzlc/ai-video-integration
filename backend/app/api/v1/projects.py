"""Finite project routes. Runtime bearer and trusted window identity are both required."""

import threading
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request

from app.api.v1.models import Uuid
from app.api.v1.projects_models import (
    ClosedSession,
    Command,
    CreatePayload,
    Draft,
    DraftSummary,
    Envelope,
    GrantPayload,
    MutationReceipt,
    OpenProject,
    Operation,
    PrivateDirectory,
    Project,
    RecentProject,
    SaveDraftPayload,
    Session,
)
from app.runtime.context import RuntimeContext
from app.services.projects import ProjectService
from app.storage.errors import ProjectError


class ProjectStore:
    """Lazy service: constructing the app or exporting OpenAPI never reads user data."""

    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self._service: ProjectService | None = None
        self._mutex = threading.Lock()

    def get(self) -> ProjectService:
        with self._mutex:
            if not self.context.ready:
                raise ProjectError("STORAGE_UNAVAILABLE", 503)
            if self._service is None:
                self._service = ProjectService(self.context.app_data_dir)
            return self._service

    def close(self) -> None:
        with self._mutex:
            if self._service is not None:
                self._service.close()
                self._service = None


def window_identity(request: Request) -> int:
    values = request.headers.getlist("x-window-id")
    if (
        len(values) != 1
        or len(values[0]) > 16
        or not values[0].isascii()
        or not values[0].isdigit()
        or not 1 <= int(values[0]) <= 9007199254740991
    ):
        raise ProjectError("REQUEST_INVALID", 400)
    return int(values[0])


def project_session(request: Request) -> str:
    sessions = request.headers.getlist("x-project-session")
    if len(sessions) != 1:
        raise ProjectError("SESSION_EXPIRED", 401)
    return sessions[0]


def project_router(store: ProjectStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["T02"])

    def result(request: Request, data: Any) -> dict[str, Any]:
        return {"requestId": request.state.request_id, "data": data}

    @router.post(
        "/file-grants", operation_id="registerFileGrant", response_model=Envelope[MutationReceipt]
    )
    def register_grant(
        request: Request, command: Command[GrantPayload], window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request, store.get().register_grant(command.model_dump(by_alias=True), window)
        )

    @router.post(
        "/projects",
        operation_id="createProject",
        status_code=201,
        response_model=Envelope[MutationReceipt],
    )
    def create(
        request: Request, command: Command[CreatePayload], window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request, store.get().create_project(command.model_dump(by_alias=True), window)
        )

    @router.post(
        "/project-sessions",
        operation_id="openProject",
        status_code=201,
        response_model=Envelope[Session],
    )
    def open_project(
        request: Request, command: OpenProject, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(request, store.get().open_project(command.model_dump(by_alias=True), window))

    @router.get(
        "/projects/{projectId}", operation_id="getProject", response_model=Envelope[Project]
    )
    def get_project(
        project_id: Annotated[Uuid, Path(alias="projectId")],
        request: Request,
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request, store.get().get_project(project_id, project_session(request), window)
        )

    @router.put(
        "/projects/{projectId}/drafts/{draftId}",
        operation_id="saveDraft",
        response_model=Envelope[MutationReceipt],
    )
    def save_draft(
        project_id: Annotated[Uuid, Path(alias="projectId")],
        draft_id: Annotated[Uuid, Path(alias="draftId")],
        request: Request,
        command: Command[SaveDraftPayload],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        if command.payload.draft_id != draft_id:
            raise ProjectError("REQUEST_INVALID", 400)
        return result(
            request,
            store.get().save_draft(
                project_id,
                project_session(request),
                window,
                draft_id,
                command.model_dump(by_alias=True),
            ),
        )

    @router.get(
        "/projects/{projectId}/drafts/{draftId}",
        operation_id="getDraft",
        response_model=Envelope[Draft],
    )
    def get_draft(
        project_id: Annotated[Uuid, Path(alias="projectId")],
        draft_id: Annotated[Uuid, Path(alias="draftId")],
        request: Request,
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request, store.get().get_draft(project_id, project_session(request), window, draft_id)
        )

    @router.get(
        "/projects/{projectId}/drafts",
        operation_id="listDrafts",
        response_model=Envelope[list[DraftSummary]],
    )
    def list_drafts(
        project_id: Annotated[Uuid, Path(alias="projectId")],
        request: Request,
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request, store.get().list_drafts(project_id, project_session(request), window)
        )

    @router.get(
        "/projects/{projectId}/operations/{operationId}",
        operation_id="getProjectOperation",
        response_model=Envelope[Operation],
    )
    def project_operation(
        project_id: Annotated[Uuid, Path(alias="projectId")],
        operation_id: Annotated[Uuid, Path(alias="operationId")],
        request: Request,
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().get_project_operation(
                project_id, project_session(request), window, operation_id
            ),
        )

    @router.get(
        "/operations/{operationId}",
        operation_id="getGlobalOperation",
        response_model=Envelope[Operation],
    )
    def operation(
        operation_id: Annotated[Uuid, Path(alias="operationId")],
        request: Request,
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(request, store.get().get_global_operation(operation_id))

    @router.get(
        "/recent-projects",
        operation_id="listRecentProjects",
        response_model=Envelope[list[RecentProject]],
    )
    def recent(request: Request, window: int = Depends(window_identity)) -> dict[str, Any]:
        return result(request, store.get().recent_projects())

    @router.get(
        "/private/recent-projects/{project_id}/directory",
        operation_id="getRecentProjectDirectory",
        response_model=Envelope[PrivateDirectory],
    )
    def directory(
        project_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(request, {"path": str(store.get().recent_project_directory(project_id))})

    @router.delete(
        "/project-sessions/{session_id}",
        operation_id="closeProjectSession",
        response_model=Envelope[ClosedSession],
    )
    def close(
        session_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        store.get().close_session(session_id, window)
        return result(request, {"closed": True})

    return router
