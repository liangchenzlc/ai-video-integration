"""Local storyboarding reads and explicit draft/order mutations."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request

from app.api.v1.models import Uuid
from app.api.v1.projects import ProjectStore, project_session, window_identity
from app.api.v1.projects_models import Command, Envelope, MutationReceipt
from app.api.v1.storyboard_models import (
    Coverage,
    PromptPreview,
    ReorderShots,
    Storyboard,
    VerifyReference,
)
from app.services.storyboard_templates import preview_for_project


def storyboard_router(store: ProjectStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/projects", tags=["T07 storyboard"])

    def result(request: Request, data: Any) -> dict[str, Any]:
        return {"requestId": request.state.request_id, "data": data}

    @router.get(
        "/{project_id}/storyboard",
        response_model=Envelope[Storyboard],
        operation_id="getStoryboard",
    )
    def get_storyboard(
        project_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request, store.get().get_storyboard(project_id, project_session(request), window)
        )

    @router.get(
        "/{project_id}/coverage",
        response_model=Envelope[Coverage],
        operation_id="getRequirementCoverage",
    )
    def coverage(
        project_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request, store.get().get_coverage(project_id, project_session(request), window)
        )

    @router.put(
        "/{project_id}/shot-order",
        response_model=Envelope[MutationReceipt],
        operation_id="reorderShots",
    )
    def reorder(
        project_id: Uuid,
        request: Request,
        command: Command[ReorderShots],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().reorder_shots(
                project_id, project_session(request), window, command.model_dump(by_alias=True)
            ),
        )

    @router.post(
        "/{project_id}/references/verification",
        response_model=Envelope[MutationReceipt],
        operation_id="verifyReference",
    )
    def verify(
        project_id: Uuid,
        request: Request,
        command: Command[VerifyReference],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().verify_reference(
                project_id, project_session(request), window, command.model_dump(by_alias=True)
            ),
        )

    @router.get(
        "/{project_id}/storyboard/shots/{shot_id}/prompt",
        response_model=Envelope[PromptPreview],
        operation_id="previewShotPrompt",
    )
    def prompt(
        project_id: Uuid,
        shot_id: Uuid,
        request: Request,
        phase: Literal["image", "video"] = "image",
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            preview_for_project(
                store.get(), project_id, project_session(request), window, shot_id, phase
            ),
        )

    return router
