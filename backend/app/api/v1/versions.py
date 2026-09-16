"""Explicit version commands and local evidence queries; no provider invocation."""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.models import Uuid
from app.api.v1.projects import ProjectStore, project_session, window_identity
from app.api.v1.projects_models import Command, Envelope, MutationReceipt
from app.api.v1.versions_models import (
    AdoptRevision,
    ArtifactState,
    CheckReport,
    ConfirmRevision,
    CreateRevision,
    Impact,
    PreviewAdoption,
    RevisionPage,
    RunLocalChecks,
    UndoAdoption,
)


def versions_router(store: ProjectStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["T05 versions"])

    def result(request: Request, data: Any) -> dict[str, Any]:
        return {"requestId": request.state.request_id, "data": data}

    @router.get(
        "/projects/{project_id}/artifacts/{artifact_id}",
        operation_id="getArtifact",
        response_model=Envelope[ArtifactState],
    )
    def get_artifact(
        project_id: Uuid,
        artifact_id: Uuid,
        request: Request,
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().get_artifact(project_id, project_session(request), window, artifact_id),
        )

    @router.get(
        "/projects/{project_id}/artifacts/{artifact_id}/revisions",
        operation_id="listRevisions",
        response_model=Envelope[RevisionPage],
    )
    def list_revisions(
        project_id: Uuid,
        artifact_id: Uuid,
        request: Request,
        cursor: Uuid | None = None,
        limit: int = Query(50, ge=1, le=200),
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().list_revisions(
                project_id,
                project_session(request),
                window,
                artifact_id,
                cursor=cursor,
                limit=limit,
            ),
        )

    @router.post(
        "/projects/{project_id}/artifacts/{artifact_id}/revisions",
        operation_id="createRevision",
        response_model=Envelope[MutationReceipt],
        status_code=201,
    )
    def create_revision(
        project_id: Uuid,
        artifact_id: Uuid,
        request: Request,
        command: Command[CreateRevision],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().create_revision(
                project_id,
                project_session(request),
                window,
                artifact_id,
                command.model_dump(by_alias=True),
            ),
        )

    @router.post(
        "/projects/{project_id}/artifacts/{artifact_id}/adoption-preview",
        operation_id="previewAdoption",
        response_model=Envelope[Impact],
    )
    def preview_adoption(
        project_id: Uuid,
        artifact_id: Uuid,
        request: Request,
        payload: PreviewAdoption,
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().preview_adoption(
                project_id,
                project_session(request),
                window,
                artifact_id,
                payload.model_dump(by_alias=True),
            ),
        )

    @router.post(
        "/projects/{project_id}/artifacts/{artifact_id}/adoptions",
        operation_id="adoptRevision",
        response_model=Envelope[MutationReceipt],
    )
    def adopt_revision(
        project_id: Uuid,
        artifact_id: Uuid,
        request: Request,
        command: Command[AdoptRevision],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().adopt_revision(
                project_id,
                project_session(request),
                window,
                artifact_id,
                command.model_dump(by_alias=True),
            ),
        )

    @router.post(
        "/projects/{project_id}/artifacts/{artifact_id}/confirmations",
        operation_id="confirmRevision",
        response_model=Envelope[MutationReceipt],
    )
    def confirm_revision(
        project_id: Uuid,
        artifact_id: Uuid,
        request: Request,
        command: Command[ConfirmRevision],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().confirm_revision(
                project_id,
                project_session(request),
                window,
                artifact_id,
                command.model_dump(by_alias=True),
            ),
        )

    @router.post(
        "/projects/{project_id}/adoptions/{adoption_id}/undo",
        operation_id="undoAdoption",
        response_model=Envelope[MutationReceipt],
    )
    def undo_adoption(
        project_id: Uuid,
        adoption_id: Uuid,
        request: Request,
        command: Command[UndoAdoption],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().undo_adoption(
                project_id,
                project_session(request),
                window,
                adoption_id,
                command.model_dump(by_alias=True),
            ),
        )

    @router.post(
        "/projects/{project_id}/local-checks",
        operation_id="runLocalChecks",
        response_model=Envelope[MutationReceipt],
        status_code=202,
    )
    def run_local_checks(
        project_id: Uuid,
        request: Request,
        command: Command[RunLocalChecks],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().run_local_checks(
                project_id, project_session(request), window, command.model_dump(by_alias=True)
            ),
        )

    @router.get(
        "/projects/{project_id}/check-reports/{check_id}",
        operation_id="getCheckReport",
        response_model=Envelope[CheckReport],
    )
    def get_check_report(
        project_id: Uuid, check_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().get_check_report(project_id, project_session(request), window, check_id),
        )

    return router
