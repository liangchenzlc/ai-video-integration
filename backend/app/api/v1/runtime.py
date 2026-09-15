import time
from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from app.api.errors import error_response
from app.api.v1.models import (
    CAPABILITY_IDS,
    CapabilitiesData,
    CapabilitiesResponse,
    Capability,
    ErrorResponse,
    HealthData,
    HealthResponse,
)
from app.runtime.context import RuntimeContext


def runtime_router(context: RuntimeContext) -> APIRouter:
    response_headers = {"X-Request-Id": {"schema": {"$ref": "#/components/schemas/Uuid"}}}
    errors: dict[int | str, dict[str, Any]] = {
        status: {"model": ErrorResponse, "headers": response_headers}
        for status in (400, 401, 403, 404, 405, 422, 500, 503)
    }
    errors[200] = {"headers": response_headers}
    router = APIRouter(prefix="/api/v1", responses=errors)
    request_metadata = {
        "parameters": [
            {
                "in": "header",
                "name": "X-Request-Id",
                "required": False,
                "schema": {"$ref": "#/components/schemas/Uuid"},
            }
        ]
    }

    @router.get(
        "/health",
        operation_id="getRuntimeHealth",
        response_model=HealthResponse,
        openapi_extra=request_metadata,
    )
    async def health(request: Request) -> HealthResponse | JSONResponse:
        if not context.ready:
            return error_response("BACKEND_NOT_READY", request.state.request_id)
        return HealthResponse(
            request_id=request.state.request_id,
            data=HealthData(
                status="ready",
                runtime_id=context.runtime_id,
                generation=context.generation,
                api_version=context.api_version,
                control_version=context.control_version,
                backend_version=context.backend_version,
                uptime_ms=max(0, int((time.monotonic() - context.started_monotonic) * 1000)),
            ),
        )

    @router.get(
        "/capabilities",
        operation_id="getRuntimeCapabilities",
        response_model=CapabilitiesResponse,
        openapi_extra=request_metadata,
    )
    async def capabilities(request: Request) -> CapabilitiesResponse | JSONResponse:
        if not context.ready:
            return error_response("BACKEND_NOT_READY", request.state.request_id)
        return CapabilitiesResponse(
            request_id=request.state.request_id,
            data=CapabilitiesData(
                runtime_id=context.runtime_id,
                generation=context.generation,
                capabilities=[
                    Capability(
                        id=identity,
                        enabled=identity == "runtime",
                        reason_code="AVAILABLE" if identity == "runtime" else "NOT_IMPLEMENTED",
                    )
                    for identity in CAPABILITY_IDS
                ],
            ),
        )

    return router
