"""Local production audio/readiness API. These routes never submit remote work."""

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.v1.models import Uuid
from app.api.v1.production_audio_models import (
    DuckingRequest,
    DuckingResult,
    ReadinessResult,
    RightsList,
    SaveRights,
    TimingRequest,
    TimingResult,
    VideoReadiness,
)
from app.api.v1.projects import ProjectStore, project_session, window_identity
from app.api.v1.projects_models import Command, Envelope, MutationReceipt


def production_audio_router(store: ProjectStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/projects", tags=["T08 T10 T11 production audio"])

    def result(request: Request, data: Any) -> dict[str, Any]:
        return {"requestId": request.state.request_id, "data": data}

    @router.post(
        "/{project_id}/timing-checks",
        response_model=Envelope[TimingResult],
        operation_id="checkTiming",
    )
    def timing(
        project_id: Uuid,
        request: Request,
        payload: TimingRequest,
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get()._production_audio.timing_check(
                project_id, project_session(request), window, payload.model_dump(by_alias=True)
            ),
        )

    @router.post(
        "/{project_id}/video-readiness",
        response_model=Envelope[ReadinessResult],
        operation_id="checkVideoReadiness",
    )
    def video_readiness(
        project_id: Uuid,
        request: Request,
        payload: VideoReadiness,
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get()._production_audio.video_readiness(
                project_id, project_session(request), window, payload.model_dump(by_alias=True)
            ),
        )

    @router.get(
        "/{project_id}/rights",
        response_model=Envelope[RightsList],
        operation_id="listRightsEvidence",
    )
    def rights(
        project_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request,
            store.get()._production_audio.list_rights(project_id, project_session(request), window),
        )

    @router.put(
        "/{project_id}/rights/{evidence_id}",
        response_model=Envelope[MutationReceipt],
        operation_id="saveRightsEvidence",
    )
    def save_rights(
        project_id: Uuid,
        evidence_id: Uuid,
        request: Request,
        command: Command[SaveRights],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get()._production_audio.save_rights(
                project_id,
                project_session(request),
                window,
                evidence_id,
                command.model_dump(by_alias=True),
            ),
        )

    @router.post(
        "/{project_id}/mix/ducking",
        response_model=Envelope[DuckingResult],
        operation_id="previewMusicDucking",
    )
    def ducking(
        project_id: Uuid,
        request: Request,
        payload: DuckingRequest,
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get()._production_audio.ducking(
                project_id, project_session(request), window, payload.model_dump(by_alias=True)
            ),
        )

    return router
