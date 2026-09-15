"""Application factory. Importing this module never binds a port or reads user data."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.api.errors import error_response
from app.api.security import RuntimeSecurity
from app.api.v1.models import ErrorCode
from app.api.v1.runtime import runtime_router
from app.runtime.context import RuntimeContext


class RuntimeApp(FastAPI):
    def openapi(self) -> dict[str, Any]:
        schema: dict[str, Any] = super().openapi()
        schema["security"] = [{"RuntimeBearer": []}]
        schema.setdefault("components", {})["securitySchemes"] = {
            "RuntimeBearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "32-byte random token, base64url without padding",
            }
        }
        return schema


def create_app(context: RuntimeContext) -> FastAPI:
    app = RuntimeApp(
        title="AI Video Integration Runtime",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        debug=False,
        redirect_slashes=False,
    )
    app.add_middleware(RuntimeSecurity, context=context)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        codes: dict[int, ErrorCode] = {
            400: "REQUEST_INVALID",
            401: "AUTH_REQUIRED",
            403: "ORIGIN_REJECTED",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            422: "REQUEST_INVALID",
            500: "INTERNAL_ERROR",
            503: "BACKEND_NOT_READY",
        }
        code = codes.get(error.status_code, "INTERNAL_ERROR")
        status = error.status_code if error.status_code in codes else 500
        return error_response(code, request.state.request_id, status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, _: RequestValidationError) -> JSONResponse:
        return error_response("REQUEST_INVALID", request.state.request_id)

    app.include_router(runtime_router(context))
    return app
