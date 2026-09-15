"""Fixed error messages; never expose exception text, validation input or traceback."""

from starlette.responses import JSONResponse

from app.api.v1.models import ErrorCode, ErrorDetail, ErrorResponse, RecoveryAction

ERRORS: dict[ErrorCode, tuple[int, str, RecoveryAction]] = {
    "AUTH_REQUIRED": (401, "本地服务连接缺少认证，请重启服务。", "restart_backend"),
    "AUTH_INVALID": (401, "本地服务认证已失效，请重启服务。", "restart_backend"),
    "HOST_REJECTED": (403, "本地服务地址不匹配。", "none"),
    "ORIGIN_REJECTED": (403, "此请求来源不允许访问本地服务。", "none"),
    "REQUEST_INVALID": (422, "请求格式不正确。", "none"),
    "NOT_FOUND": (404, "请求的接口不存在。", "none"),
    "METHOD_NOT_ALLOWED": (405, "此接口不支持该请求方式。", "none"),
    "BACKEND_NOT_READY": (503, "本地服务尚未就绪。", "retry_connection"),
    "INTERNAL_ERROR": (500, "本地服务遇到错误，请重启后重试。", "restart_backend"),
}


def error_response(code: ErrorCode, request_id: str, status: int | None = None) -> JSONResponse:
    default_status, message, recovery = ERRORS[code]
    body = ErrorResponse(
        request_id=request_id,
        error=ErrorDetail(code=code, message=message, affected_ids=[], recoverable_action=recovery),
    )
    return JSONResponse(body.model_dump(by_alias=True), status_code=status or default_status)
