"""Finite settings routes; no endpoint can read a stored credential secret."""

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.v1.media_models import Job
from app.api.v1.models import Uuid
from app.api.v1.projects import ProjectStore, project_session, window_identity
from app.api.v1.projects_models import Command, Envelope, MutationReceipt
from app.api.v1.settings_models import (
    ConfigureStage,
    ConfigureStorage,
    ConnectionCheck,
    DeleteCredential,
    ProviderId,
    SetCredential,
    SettingsDetails,
    StageModel,
)


def settings_router(store: ProjectStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["T03 settings"])

    def result(request: Request, data: Any) -> dict[str, Any]:
        return {"requestId": request.state.request_id, "data": data}

    @router.get(
        "/settings/details",
        operation_id="getSettingsDetails",
        response_model=Envelope[SettingsDetails],
    )
    def details(request: Request, window: int = Depends(window_identity)) -> dict[str, Any]:
        return result(request, store.get().get_settings_details())

    @router.put(
        "/credentials/{provider_id}",
        operation_id="setCredential",
        response_model=Envelope[MutationReceipt],
    )
    def set_credential(
        provider_id: ProviderId,
        request: Request,
        command: Command[SetCredential],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().set_credential(provider_id, command.model_dump(by_alias=True), window),
        )

    @router.post(
        "/credentials/{provider_id}/delete",
        operation_id="deleteCredential",
        response_model=Envelope[MutationReceipt],
    )
    def delete_credential(
        provider_id: ProviderId,
        request: Request,
        command: Command[DeleteCredential],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().delete_credential(provider_id, command.model_dump(by_alias=True), window),
        )

    @router.put(
        "/settings/storage",
        operation_id="configureStorage",
        response_model=Envelope[MutationReceipt],
    )
    def storage(
        request: Request, command: Command[ConfigureStorage], window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request, store.get().configure_storage(command.model_dump(by_alias=True), window)
        )

    @router.get(
        "/projects/{project_id}/stage-models",
        operation_id="getStageModels",
        response_model=Envelope[list[StageModel]],
    )
    def stages(
        project_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request, store.get().get_stage_models(project_id, project_session(request), window)
        )

    @router.put(
        "/projects/{project_id}/stage-models",
        operation_id="configureStageModel",
        response_model=Envelope[MutationReceipt],
    )
    def stage(
        project_id: Uuid,
        request: Request,
        command: Command[ConfigureStage],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().configure_stage(
                project_id, project_session(request), window, command.model_dump(by_alias=True)
            ),
        )

    @router.post(
        "/connection-checks",
        operation_id="checkConnection",
        status_code=202,
        response_model=Envelope[MutationReceipt],
    )
    def check(
        request: Request, command: Command[ConnectionCheck], window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request, store.get().check_connection(command.model_dump(by_alias=True), window)
        )

    @router.get("/jobs/{job_id}", operation_id="getGlobalJob", response_model=Envelope[Job])
    def job(
        job_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(request, store.get().get_global_job(job_id))

    return router
