import json

import pytest
from app.api.security import RuntimeSecurity
from fastapi import FastAPI, Request

from tests.api.test_runtime import client, make_context


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def echo_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RuntimeSecurity, context=make_context())

    @app.post("/api/v1/projects")
    async def echo(request: Request) -> dict[str, object]:
        return {"requestId": request.state.request_id, "data": await request.json()}

    return app


@pytest.mark.anyio
async def test_business_json_accepts_more_than_runtime_limit() -> None:
    payload = {"text": "本地项目" * 12000}
    async with client(echo_app()) as http:
        response = await http.post("/api/v1/projects", json=payload)
    assert response.status_code == 200
    assert response.json()["data"] == payload


@pytest.mark.anyio
@pytest.mark.parametrize(
    "source",
    [b'{"a":1,"a":2}', b'{"a":{"x":1,"x":2}}', b'{"a":NaN}', b'{"a":"\\ud800"}', b'{"a":"\xff"}'],
)
async def test_ambiguous_or_invalid_json_rejected_before_business_handler(source: bytes) -> None:
    async with client(echo_app()) as http:
        response = await http.post(
            "/api/v1/projects", content=source, headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUEST_INVALID"


@pytest.mark.anyio
async def test_business_limit_is_one_mib_and_runtime_rules_remain() -> None:
    async with client(echo_app()) as http:
        too_large = await http.post("/api/v1/projects", json={"text": "x" * (1024 * 1024)})
        runtime_body = await http.request("GET", "/api/v1/health", json={"a": 1})
        arbitrary = await http.post("/api/v1/not-a-business-route", json={"a": 1})
        wrong_type = await http.post("/api/v1/projects", content=json.dumps({"a": 1}))
    assert too_large.status_code == 413
    assert runtime_body.status_code == 400
    assert arbitrary.status_code == 400
    assert wrong_type.status_code == 400
