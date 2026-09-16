import base64
import copy
import json
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from app.api.v1.models import (
    CAPABILITY_IDS,
    UUID_PATTERN,
    CapabilitiesResponse,
    HealthResponse,
)
from app.main import create_app
from app.runtime.context import RuntimeContext
from fastapi import FastAPI
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from starlette.exceptions import HTTPException

ROOT = Path(__file__).resolve().parents[3]
DESIGN = json.loads((ROOT / "docs/技术方案/契约/t01-http.openapi.json").read_text(encoding="utf-8"))
EXAMPLES = json.loads(
    (ROOT / "docs/技术方案/契约/t01-http.examples.json").read_text(encoding="utf-8")
)
TOKEN = b"TEST_ONLY_SECRET_SENTINEL".ljust(32, b"_")
AUTH = "Bearer " + base64.urlsafe_b64encode(TOKEN).decode().rstrip("=")
REQUEST_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def make_context() -> RuntimeContext:
    return RuntimeContext(
        runtime_id="22222222-2222-4222-8222-222222222222",
        generation=1,
        token_bytes=TOKEN,
        app_data_dir=ROOT / ".cache/test-app",
        mode="production",
        port=49152,
        ready=True,
        started_monotonic=time.monotonic() - 1,
    )


@pytest.fixture
def context() -> RuntimeContext:
    return make_context()


def client(app: FastAPI, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:49152",
        headers=headers
        if headers is not None
        else {"Authorization": AUTH, "X-Request-Id": REQUEST_ID},
        trust_env=False,
    )


def matches_design(data: dict[str, object], name: str) -> None:
    schema = {"$ref": f"#/components/schemas/{name}", "components": DESIGN["components"]}
    Draft202012Validator(schema).validate(data)


def assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    matches_design(body, "ErrorResponse")
    assert body["error"]["code"] == code
    assert body["error"]["affectedIds"] == []
    assert response.headers["x-request-id"] == body["requestId"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "access-control-allow-origin" not in response.headers
    assert TOKEN.decode() not in response.text
    assert AUTH not in response.text


@pytest.mark.anyio
async def test_health_and_capability_identity(context: RuntimeContext) -> None:
    async with client(create_app(context)) as http:
        health = await http.get("/api/v1/health")
        assert health.status_code == 200
        matches_design(health.json(), "HealthResponse")
        data = health.json()["data"]
        assert data["runtimeId"] == context.runtime_id
        assert data["generation"] == context.generation
        assert 900 <= data["uptimeMs"] < 10000
        assert health.json()["requestId"] == REQUEST_ID == health.headers["x-request-id"]
        response = await http.get("/api/v1/capabilities")
        matches_design(response.json(), "CapabilitiesResponse")
        caps = response.json()["data"]["capabilities"]
        assert [item["id"] for item in caps] == list(CAPABILITY_IDS)
        assert [item["id"] for item in caps if item["enabled"]] == ["runtime", "projects"]
        expected = copy.deepcopy(EXAMPLES["capabilities"]["data"]["capabilities"])
        expected[1].update(enabled=True, reasonCode="AVAILABLE")
        assert caps == expected


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    ["/api/v1/health", "/api/v1/capabilities", "/unknown", "/docs", "/redoc", "/openapi.json"],
)
async def test_all_routes_require_auth(context: RuntimeContext, path: str) -> None:
    async with client(create_app(context), {}) as http:
        assert_error(await http.get(path), 401, "AUTH_REQUIRED")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers,status,code",
    [
        ({"Host": "localhost:49152"}, 403, "HOST_REJECTED"),
        ({"Host": "127.0.0.1:49153"}, 403, "HOST_REJECTED"),
        ({"Host": "evil.invalid", "Origin": "null"}, 403, "HOST_REJECTED"),
        ({"Origin": "null"}, 403, "ORIGIN_REJECTED"),
        ({"Origin": "http://127.0.0.1:49152"}, 403, "ORIGIN_REJECTED"),
        ({"Authorization": "Bearer wrong"}, 401, "AUTH_INVALID"),
        ({"Authorization": "x" * 129}, 401, "AUTH_INVALID"),
        ({"Authorization": "bearer " + AUTH[7:]}, 401, "AUTH_INVALID"),
        ({"X-Request-Id": "invalid-secret-input"}, 422, "REQUEST_INVALID"),
        (
            {"X-Request-Id": REQUEST_ID.upper().replace("11111111", "ABCDEFAB", 1)},
            422,
            "REQUEST_INVALID",
        ),
    ],
)
async def test_header_checks(
    context: RuntimeContext, headers: dict[str, str], status: int, code: str
) -> None:
    async with client(create_app(context)) as http:
        response = await http.get("/api/v1/health", headers=headers)
        assert_error(response, status, code)
        assert "invalid-secret-input" not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers,status,code",
    [
        ([("Host", "127.0.0.1:49152"), ("Host", "127.0.0.1:49152")], 403, "HOST_REJECTED"),
        ([("Authorization", AUTH), ("Authorization", AUTH)], 400, "REQUEST_INVALID"),
        ([("X-Request-Id", REQUEST_ID), ("X-Request-Id", REQUEST_ID)], 422, "REQUEST_INVALID"),
    ],
)
async def test_duplicate_security_headers(
    context: RuntimeContext, headers: list[tuple[str, str]], status: int, code: str
) -> None:
    async with client(create_app(context)) as http:
        assert_error(await http.get("/api/v1/health", headers=headers), status, code)


@pytest.mark.anyio
async def test_generated_request_id_and_disabled_docs(context: RuntimeContext) -> None:
    async with client(create_app(context), {"Authorization": AUTH}) as http:
        response = await http.get("/api/v1/health")
        assert re.fullmatch(UUID_PATTERN, response.json()["requestId"])
        for path in ("/docs", "/redoc", "/openapi.json", "/unknown", "/api/v1/health/"):
            assert_error(await http.get(path), 404, "NOT_FOUND")
        assert_error(await http.post("/api/v1/health"), 405, "METHOD_NOT_ALLOWED")


@pytest.mark.anyio
async def test_parameters_body_and_readiness(context: RuntimeContext) -> None:
    async with client(create_app(context)) as http:
        assert_error(await http.get("/api/v1/health?unknown=secret"), 422, "REQUEST_INVALID")
        assert_error(
            await http.request("GET", "/api/v1/health", content=b"secret"), 400, "REQUEST_INVALID"
        )
        large = await http.request("GET", "/api/v1/health", content=b"x" * 65537)
        assert large.status_code == 413
        assert large.headers["connection"] == "close"
        assert large.content == b""
        context.ready = False
        for path in ("/api/v1/health", "/api/v1/capabilities"):
            assert_error(await http.get(path), 503, "BACKEND_NOT_READY")


@pytest.mark.anyio
async def test_exception_text_does_not_escape(
    context: RuntimeContext, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(context)

    @app.get("/fail")
    async def fail() -> None:
        raise RuntimeError(TOKEN.decode() + AUTH)

    async with client(app) as http:
        assert_error(await http.get("/fail"), 500, "INTERNAL_ERROR")
    assert TOKEN.decode() not in caplog.text
    assert AUTH not in caplog.text
    assert TOKEN.decode() not in repr(context)


@pytest.mark.anyio
async def test_http_exception_details_and_response_validation_are_sanitized(
    context: RuntimeContext,
) -> None:
    app = create_app(context)

    @app.get("/http-error")
    async def http_error() -> None:
        raise HTTPException(500, detail=AUTH)

    @app.get("/invalid-response", response_model=HealthResponse)
    async def invalid_response() -> dict[str, str]:
        return {"unexpected": AUTH}

    async with client(app) as http:
        for path in ("/http-error", "/invalid-response"):
            assert_error(await http.get(path), 500, "INTERNAL_ERROR")


@pytest.mark.anyio
async def test_chunked_body_limit_and_oversized_length_header(context: RuntimeContext) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(5):
            yield b"x" * 16384

    async with client(create_app(context)) as http:
        response = await http.request("GET", "/api/v1/health", content=chunks())
        assert response.status_code == 413
        assert response.content == b""
        assert_error(
            await http.get("/api/v1/health", headers={"Content-Length": "9" * 5000}),
            400,
            "REQUEST_INVALID",
        )
        assert_error(
            await http.get("/api/v1/health", headers={"Content-Length": "5"}),
            400,
            "REQUEST_INVALID",
        )


def test_models_accept_design_examples_and_integer_json_semantics() -> None:
    HealthResponse.model_validate(EXAMPLES["health"])
    CapabilitiesResponse.model_validate(EXAMPLES["capabilities"])
    value = copy.deepcopy(EXAMPLES["health"])
    value["data"]["generation"] = 1.0
    assert HealthResponse.model_validate(value).data.generation == 1


@pytest.mark.parametrize("bad", [True, "1", 1.5, float("nan"), float("inf"), 0, 2147483648])
def test_models_reject_invalid_generation(bad: object) -> None:
    value = copy.deepcopy(EXAMPLES["health"])
    value["data"]["generation"] = bad
    with pytest.raises(ValidationError):
        HealthResponse.model_validate(value)


def test_capabilities_cannot_claim_unimplemented_or_duplicate_features() -> None:
    value = copy.deepcopy(EXAMPLES["capabilities"])
    value["data"]["capabilities"][1]["enabled"] = True
    with pytest.raises(ValidationError):
        CapabilitiesResponse.model_validate(value)
    value = copy.deepcopy(EXAMPLES["capabilities"])
    value["data"]["capabilities"][1] = value["data"]["capabilities"][0]
    with pytest.raises(ValidationError):
        CapabilitiesResponse.model_validate(value)
