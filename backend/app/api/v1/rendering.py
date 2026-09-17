"""Explicit timeline previews and local encoding requests; all paths stay private."""

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.v1.models import Uuid
from app.api.v1.projects import ProjectStore, project_session, window_identity
from app.api.v1.projects_models import Command, Envelope, MutationReceipt
from app.api.v1.rendering_models import (
    ExportFilm,
    ExportRecord,
    RenderAnimatic,
    RenderPlan,
    RenderPlanPreview,
    ReplacementImpact,
    ReplacementPreview,
    TimelineEdit,
    TimelineEditResult,
)


def rendering_router(store: ProjectStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/projects", tags=["T09 T12 rendering"])

    def result(request: Request, data: Any) -> dict[str, Any]:
        return {"requestId": request.state.request_id, "data": data}

    @router.post(
        "/{project_id}/animatics",
        operation_id="renderAnimatic",
        response_model=Envelope[MutationReceipt],
        status_code=202,
    )
    def animatic(
        project_id: Uuid,
        request: Request,
        command: Command[RenderAnimatic],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get()._rendering.render_animatic(
                project_id, project_session(request), window, command.model_dump(by_alias=True)
            ),
        )

    @router.post(
        "/{project_id}/exports",
        operation_id="exportFilm",
        response_model=Envelope[MutationReceipt],
        status_code=202,
    )
    def export(
        project_id: Uuid,
        request: Request,
        command: Command[ExportFilm],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get()._rendering.export_film(
                project_id, project_session(request), window, command.model_dump(by_alias=True)
            ),
        )

    @router.get(
        "/{project_id}/exports/{export_id}",
        operation_id="getExport",
        response_model=Envelope[ExportRecord],
    )
    def get_export(
        project_id: Uuid, export_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request,
            store.get()._rendering.get_export(
                project_id, project_session(request), window, export_id
            ),
        )

    @router.post(
        "/{project_id}/render-plan-preview",
        operation_id="previewRenderPlan",
        response_model=Envelope[RenderPlan],
    )
    def preview(
        project_id: Uuid,
        request: Request,
        payload: RenderPlanPreview,
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get()._rendering.preview_render_plan(
                project_id,
                project_session(request),
                window,
                payload.model_dump(by_alias=True, exclude_unset=True),
            ),
        )

    @router.get(
        "/{project_id}/render-plans/{plan_id}",
        operation_id="getRenderPlan",
        response_model=Envelope[RenderPlan],
    )
    def get_plan(
        project_id: Uuid, plan_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request,
            store.get()._rendering.get_render_plan(
                project_id, project_session(request), window, plan_id
            ),
        )

    @router.post(
        "/{project_id}/timeline/replacement-preview",
        operation_id="previewTimelineReplacement",
        response_model=Envelope[ReplacementImpact],
    )
    def replacement(
        project_id: Uuid,
        request: Request,
        payload: ReplacementPreview,
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get()._rendering.replacement_preview(
                project_id, project_session(request), window, payload.model_dump(by_alias=True)
            ),
        )

    @router.post(
        "/{project_id}/timeline/edit-preview",
        operation_id="previewTimelineEdit",
        response_model=Envelope[TimelineEditResult],
    )
    def edit(
        project_id: Uuid,
        request: Request,
        payload: TimelineEdit,
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get()._rendering.edit_timeline(
                project_id,
                project_session(request),
                window,
                payload.model_dump(by_alias=True, exclude_unset=True),
            ),
        )

    return router
