"""Application factory. Importing this module never binds a port or reads user data."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.api.errors import error_response
from app.api.security import RuntimeSecurity
from app.api.v1.media import media_router
from app.api.v1.models import ErrorCode
from app.api.v1.production import production_router
from app.api.v1.production_audio import production_audio_router
from app.api.v1.projects import ProjectStore, project_router
from app.api.v1.rendering import rendering_router
from app.api.v1.runtime import runtime_router
from app.api.v1.settings import settings_router
from app.api.v1.storyboard import storyboard_router
from app.api.v1.tasks import tasks_router
from app.api.v1.versions import versions_router
from app.runtime.context import RuntimeContext
from app.storage.errors import ProjectError


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
    projects = ProjectStore(context)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            projects.close()

    app = RuntimeApp(
        title="AI Video Integration Runtime",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        debug=False,
        redirect_slashes=False,
        lifespan=lifespan,
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

    @app.exception_handler(ProjectError)
    async def project_error(request: Request, error: ProjectError) -> JSONResponse:
        messages = {
            "REQUEST_INVALID": "项目请求无效，请重新操作。",
            "VALIDATION_FAILED": "请检查输入内容与所选配置。",
            "GRANT_REJECTED": "目录授权已失效，请重新选择目录。",
            "SESSION_EXPIRED": "项目会话已失效，请重新打开项目。",
            "PROJECT_READ_ONLY": "项目当前只读，请关闭占用它的窗口后重新打开。",
            "PROJECT_BUSY": "项目正在使用，请关闭占用窗口后重试。",
            "OPERATION_ID_REUSED": "该操作编号已用于其他内容，请核对原操作。",
            "REVISION_CONFLICT": "内容已更新，请核对已保存的内容。",
            "DIRECTORY_NOT_EMPTY": "所选目录不是空目录，请选择新的空目录。",
            "PROJECT_NOT_FOUND": "未找到项目，请重新选择项目目录。",
            "OBJECT_NOT_FOUND": "未找到该项目记录，请重新打开项目。",
            "PROJECT_CORRUPT": "项目数据库无法读取，原文件已保留。",
            "PROJECT_VERSION_UNSUPPORTED": "此项目格式与当前应用不兼容。",
            "PROJECT_RECOVERY_REQUIRED": "项目创建尚未完成，已保留文件，请核对原操作。",
            "UNSAFE_PROJECT_PATH": "请使用本机普通目录，避开网络、同步或链接目录。",
            "STORAGE_UNAVAILABLE": "无法访问本地存储，请检查磁盘空间与目录权限。",
            "MEDIA_TOOLS_NOT_CONFIGURED": "请先选择本机 FFmpeg 工具。",
            "MEDIA_TOOLS_UNAVAILABLE": "无法启动媒体工具，请重新选择 FFmpeg。",
            "MEDIA_TOOLS_MISMATCH": "FFmpeg 与 ffprobe 不匹配，请选择同一构建的工具。",
            "MEDIA_TOOLS_CAPABILITY_MISSING": "媒体工具缺少 H.264、AAC 或字幕编码支持。",
            "MEDIA_FORMAT_UNSUPPORTED": "请选择支持的图片、音频或视频格式。",
            "MEDIA_SIZE_LIMIT": "单个媒体文件不能超过 2 GiB。",
            "MEDIA_PIXEL_LIMIT": "图片尺寸超过 4,000 万像素。",
            "MEDIA_INVALID": "媒体无法完整解码，原文件已保留。",
            "MEDIA_PROBE_TIMEOUT": "媒体检查超时，原文件已保留。",
            "MEDIA_TOOL_OUTPUT_LIMIT": "媒体工具返回数据超限，检查已停止。",
            "INSUFFICIENT_DISK_SPACE": "项目磁盘空间不足，请腾出空间后重试。",
            "MEDIA_SOURCE_CHANGED": "导入期间源文件发生变化，请重新选择。",
            "MEDIA_HASH_MISMATCH": "文件内容不同，不能作为原素材恢复。请导入为新素材。",
            "MEDIA_RECOVERY_REQUIRED": "导入中断，文件已保留，请核对原作业。",
            "MEDIA_MISSING": "素材文件缺失，请重新定位原文件。",
            "MEDIA_UNAVAILABLE": "素材当前不可用，原记录已保留。",
            "JOB_NOT_CANCELLABLE": "作业已结束，无法取消。",
            "JOB_CANCELLED": "作业已取消，原文件已保留。",
            "JOB_INTERRUPTED": "作业中断，请核对原结果。",
            "BACKUP_FAILED": "项目备份未通过检查，旧数据库已保留。",
            "CREDENTIAL_ENCRYPTION_FAILED": (
                "无法加密凭据，未保存密钥。可重新录入并选择仅本次使用。"
            ),
            "CREDENTIAL_DECRYPTION_FAILED": "无法解密凭据，请在当前 Windows 账户重新录入。",
            "CREDENTIAL_UNAVAILABLE": "凭据不可用，请重新录入。",
            "CREDENTIAL_NOT_FOUND": "尚未配置该服务的凭据。",
            "CREDENTIAL_KIND_MISMATCH": "凭据类型与这项服务不匹配。",
            "CREDENTIAL_IN_USE": "凭据仍被存储配置使用，请先处理关联配置。",
            "CREDENTIAL_CONFIRMATION_REQUIRED": "请确认删除这项凭据。",
            "STORAGE_CREDENTIAL_INVALID": "请选择属于该存储服务的 OSS 凭据。",
            "STORAGE_PERSISTENCE_MISMATCH": "长期存储配置需要加密保存的凭据。",
            "CAPABILITY_UNAVAILABLE": "当前模型能力不可用，请查看账户、接口和效果状态。",
            "CAPABILITY_PHASE_MISMATCH": "该模型不支持所选制作阶段。",
            "CONNECTION_CHECK_UNAVAILABLE": "此能力尚无已核定的免费连接检测，未发送模型请求。",
            "CONNECTION_CHECK_FAILED": "连接检测未通过，请核对账户权限、地域和型号。",
            "PROJECT_MIGRATION_FAILED": "项目升级失败，原数据库与备份已保留。",
            "INPUT_INCOMPLETE": (
                "创建正式版本、采用、确认或生成前请补齐所需内容；未完成草稿仍可保存。"
            ),
            "INPUT_LOCKED": "任务正在使用这些内容，请等待任务结束后再采用。",
            "REVISION_SIZE_LIMIT": "正式版本内容超过 700 KiB，请精简内容后重试；草稿已保留。",
            "PREVIEW_STALE": "内容或影响已变化，请重新预览后采用。",
            "DEPENDENCY_CYCLE": "版本引用形成循环，请调整引用后重试。",
            "CHECK_REQUIRED": "请先对当前版本完成必要检查，再确认。",
            "UNDO_CONFLICT": "相关内容已有后续修改，无法撤销这次采用。",
            "PLAN_STALE": "输入、配置或计划有效期已改变，请重新预览计划。",
            "CAPABILITY_MISSING": "尚无满足要求的模型与价格档案，请先配置已验证能力。",
            "BUDGET_EXCEEDED": "本次操作超出项目、阶段或任务预算，请核对费用和上限。",
            "TASK_BUSY": "已有主动任务，请先查看或处理该任务。",
            "RECOVERY_NOT_ALLOWED": "当前状态不支持这个恢复动作，请核对原调用记录。",
            "EXECUTION_MODE_MISMATCH": "练习与真实生成不能混在同一项目，请新建对应项目。",
        }
        messages.update(
            json.loads(
                (Path(__file__).parent / "schemas/production-errors.json").read_text("utf-8")
            )
        )
        code = error.code if error.code in messages else "STORAGE_UNAVAILABLE"
        action = "reopen_project" if code == "SESSION_EXPIRED" else "none"
        return JSONResponse(
            {
                "requestId": request.state.request_id,
                "error": {
                    "code": code,
                    "message": messages[code],
                    "affectedIds": [],
                    "recoverableAction": action,
                },
            },
            status_code=error.status_code if error.code in messages else 503,
        )

    app.include_router(runtime_router(context))
    app.include_router(project_router(projects))
    app.include_router(media_router(projects))
    app.include_router(settings_router(projects))
    app.include_router(tasks_router(projects))
    app.include_router(versions_router(projects))
    app.include_router(storyboard_router(projects))
    app.include_router(production_router(projects))
    app.include_router(production_audio_router(projects))
    app.include_router(rendering_router(projects))
    return app
