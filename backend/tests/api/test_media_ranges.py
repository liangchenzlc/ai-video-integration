from pathlib import Path
from uuid import uuid4

import pytest
from app.api.security import RuntimeSecurity
from app.api.v1.media import byte_range, media_response
from fastapi import FastAPI, Request

from tests.api.test_runtime import client, make_context


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    "header, expected",
    [
        (None, (0, 9)),
        ("bytes=2-5", (2, 5)),
        ("bytes=7-", (7, 9)),
        ("bytes=-3", (7, 9)),
        ("bytes=0-999", (0, 9)),
        ("bytes=-999", (0, 9)),
    ],
)
def test_single_byte_range(header: str | None, expected: tuple[int, int]) -> None:
    assert byte_range(header, 10) == expected


@pytest.mark.parametrize(
    "header",
    [
        "bytes=10-",
        "bytes=4-2",
        "bytes=-0",
        "bytes=0-1,4-5",
        "items=0-1",
        "bytes=",
        "bytes=999999999999999999999-",
    ],
)
def test_invalid_or_multiple_ranges_rejected(header: str) -> None:
    assert byte_range(header, 10) is None


@pytest.mark.anyio
async def test_authenticated_binary_stream_exceeds_json_limit_and_serves_ranges(
    tmp_path: Path,
) -> None:
    source = tmp_path / "image.png"
    data = b"0123456789" * 20000
    source.write_bytes(data)
    app = FastAPI()
    app.add_middleware(RuntimeSecurity, context=make_context())
    path = f"/api/v1/projects/{uuid4()}/media/{uuid4()}"

    @app.api_route(path, methods=["GET", "HEAD"])
    def serve(request: Request):
        return media_response(
            request, source, {"mime": "image/png", "byteLength": len(data), "sha256": "a" * 64}
        )

    async with client(app) as http:
        response = await http.get(path)
        assert response.status_code == 200
        assert response.content == data
        assert response.headers["content-type"] == "image/png"
        assert response.headers["accept-ranges"] == "bytes"
        selected = await http.get(path, headers={"Range": "bytes=3-7"})
        assert selected.status_code == 206
        assert selected.content == b"34567"
        assert selected.headers["content-range"] == f"bytes 3-7/{len(data)}"
        suffix = await http.get(path, headers={"Range": "bytes=-4"})
        assert suffix.content == b"6789"
        head = await http.head(path)
        assert head.status_code == 200 and not head.content
        assert head.headers["content-length"] == str(len(data))
        invalid = await http.get(path, headers={"Range": "bytes=0-1,3-4"})
        assert invalid.status_code == 416
        assert invalid.headers["content-range"] == f"bytes */{len(data)}"
