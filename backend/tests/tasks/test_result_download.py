import http.client
import io
import ssl
import threading
from pathlib import Path
from typing import Any

import pytest
from app.services import result_download
from app.storage.errors import ProjectError

HOST = "dashscope-result.oss-cn-beijing.aliyuncs.com"
URL = f"https://{HOST}/result.png?signature=private"


class Response(io.BytesIO):
    def __init__(self, data: bytes = b"png", status: int = 200, **headers: str):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Type": "image/png", **headers}

    def getheader(self, name: str, default: Any = None) -> Any:
        return self.headers.get(name, default)


class Connection:
    def __init__(self, response: Response):
        self.response = response
        self.sock = None
        self.requests: list[Any] = []

    def request(self, method: str, target: str, headers: Any) -> None:
        self.requests.append((method, target, headers))

    def getresponse(self) -> Response:
        return self.response

    def close(self) -> None:
        pass


def transport(monkeypatch: Any, *responses: Response) -> list[Any]:
    calls: list[Any] = []
    remaining = iter(responses)
    monkeypatch.setattr(result_download, "_resolve", lambda host, timeout: ["8.8.8.8"])

    def connect(host: str, address: str, timeout: float) -> Connection:
        connection = Connection(next(remaining))
        calls.append((host, address, connection))
        return connection

    monkeypatch.setattr(result_download, "_connection", connect)
    return calls


@pytest.mark.parametrize(
    "url",
    [
        "http://" + HOST + "/x",
        "https://user:secret@" + HOST + "/x",
        "https://" + HOST + ":444/x",
        "https://127.0.0.1/x",
        "https://evil.aliyuncs.com/x",
        "https://" + HOST + ".evil.test/x",
        "https://" + HOST + "/x#fragment",
        "https://" + HOST + "/x\r\nX: yes",
    ],
)
def test_rejects_uncontrolled_urls_before_connection(
    monkeypatch: Any, tmp_path: Path, url: str
) -> None:
    calls = transport(monkeypatch)
    with pytest.raises(ProjectError, match="RESULT_URL_REJECTED"):
        result_download.download_image(url, tmp_path / "result.png")
    assert not calls
    assert not (tmp_path / "result.png").exists()


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "100.64.0.1"]
)
def test_mixed_dns_is_rejected_before_connect(
    monkeypatch: Any, tmp_path: Path, address: str
) -> None:
    calls = transport(monkeypatch)
    monkeypatch.setattr(result_download, "_resolve", lambda host, timeout: ["8.8.8.8", address])
    with pytest.raises(ProjectError, match="RESULT_URL_REJECTED"):
        result_download.download_image(URL, tmp_path / "result.png")
    assert not calls


def test_redirect_to_loopback_never_connects(monkeypatch: Any, tmp_path: Path) -> None:
    calls = transport(monkeypatch, Response(status=302, Location="https://127.0.0.1/secret"))
    with pytest.raises(ProjectError, match="RESULT_URL_REJECTED"):
        result_download.download_image(URL, tmp_path / "result.png")
    assert len(calls) == 1
    assert not (tmp_path / "result.png").exists()


def test_public_download_pins_dns_and_does_not_forward_credentials(
    monkeypatch: Any, tmp_path: Path
) -> None:
    calls = transport(monkeypatch, Response(b"hello", **{"Content-Length": "5"}))
    target = tmp_path / "image.png"
    result = result_download.download_image(URL, target)
    assert target.read_bytes() == b"hello"
    assert result == {
        "mime": "image/png",
        "byteLength": 5,
        "sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
    }
    assert calls[0][:2] == (HOST, "8.8.8.8")
    headers = calls[0][2].requests[0][2]
    assert not any(key.lower() in {"authorization", "cookie"} for key in headers)
    assert "signature" not in str(result)


@pytest.mark.parametrize(
    "response",
    [
        Response(b"12345", **{"Content-Length": "5"}),
        Response(b"12345"),
        Response(b"x", **{"Content-Type": "text/html"}),
        Response(b"x", **{"Content-Length": "3"}),
        Response(b"x", **{"Content-Encoding": "gzip"}),
        Response(b""),
    ],
)
def test_bad_or_oversize_body_removes_partial_file(
    monkeypatch: Any, tmp_path: Path, response: Response
) -> None:
    transport(monkeypatch, response)
    target = tmp_path / "image.png"
    with pytest.raises(ProjectError):
        result_download.download_image(URL, target, max_bytes=4)
    assert not target.exists()


def test_tls_failure_is_static_and_keeps_existing_files(monkeypatch: Any, tmp_path: Path) -> None:
    transport(monkeypatch)

    def fail(*args: Any) -> Any:
        raise ssl.SSLCertVerificationError("private URL and signature")

    monkeypatch.setattr(result_download, "_connection", fail)
    with pytest.raises(ProjectError, match="^RESULT_DOWNLOAD_FAILED$"):
        result_download.download_image(URL, tmp_path / "image.png")


def test_existing_target_is_not_overwritten_or_removed(monkeypatch: Any, tmp_path: Path) -> None:
    transport(monkeypatch, Response(b"new"))
    target = tmp_path / "image.png"
    target.write_bytes(b"original")
    with pytest.raises(ProjectError, match="RESULT_DOWNLOAD_FAILED"):
        result_download.download_image(URL, target)
    assert target.read_bytes() == b"original"


def test_redirect_rechecks_dns_even_on_same_host(monkeypatch: Any, tmp_path: Path) -> None:
    calls = transport(monkeypatch, Response(status=302, Location="/next"))
    addresses = iter([["8.8.8.8"], ["127.0.0.1"]])
    monkeypatch.setattr(result_download, "_resolve", lambda host, timeout: next(addresses))
    with pytest.raises(ProjectError, match="RESULT_URL_REJECTED"):
        result_download.download_image(URL, tmp_path / "image.png")
    assert len(calls) == 1


def test_redirect_loop_is_bounded(monkeypatch: Any, tmp_path: Path) -> None:
    calls = transport(monkeypatch, *(Response(status=302, Location="/next") for _ in range(4)))
    with pytest.raises(ProjectError, match="RESULT_URL_REJECTED"):
        result_download.download_image(URL, tmp_path / "image.png")
    assert len(calls) == 4


def test_pinned_socket_uses_original_hostname_for_certificate_verification(
    monkeypatch: Any,
) -> None:
    addresses: list[Any] = []
    names: list[str] = []

    class Socket:
        def settimeout(self, timeout: float) -> None:
            pass

        def connect(self, address: Any) -> None:
            addresses.append(address)

        def close(self) -> None:
            pass

    class TLS:
        def wrap_socket(
            self, sock: Any, *, server_hostname: str, do_handshake_on_connect: bool
        ) -> Any:
            names.append(server_hostname)
            raise ssl.SSLCertVerificationError("hostname mismatch")

    monkeypatch.setattr(result_download.socket, "socket", lambda *args: Socket())
    connection = result_download._connection(HOST, "8.8.8.8", 1)
    assert connection.tls_context.check_hostname is True
    assert connection.tls_context.verify_mode == ssl.CERT_REQUIRED
    connection.tls_context = TLS()  # type: ignore[assignment]
    with pytest.raises(ssl.SSLCertVerificationError):
        connection.connect()
    assert addresses == [("8.8.8.8", 443)]
    assert names == [HOST]


def test_deadline_interrupts_chunk_headers_after_connection_detaches(
    monkeypatch: Any, tmp_path: Path
) -> None:
    interrupted = threading.Event()
    headers = (
        b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n"
        b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
    )

    class Wire(io.BytesIO):
        def readline(self, *args: Any) -> bytes:
            if self.tell() >= len(headers):
                if not interrupted.wait(0.4):
                    pytest.fail("total deadline failed to interrupt detached socket")
                raise TimeoutError
            return super().readline(*args)

    class Sock:
        def makefile(self, *args: Any) -> Any:
            return Wire(headers + b"1\r\nx\r\n0\r\n\r\n")

        def close(self) -> None:
            pass

        def shutdown(self, how: int) -> None:
            interrupted.set()

    connection = http.client.HTTPConnection(HOST)
    connection.sock = Sock()  # type: ignore[assignment]
    connection._HTTPConnection__state = http.client._CS_REQ_SENT  # type: ignore[attr-defined]
    monkeypatch.setattr(connection, "request", lambda *args, **kwargs: None)
    monkeypatch.setattr(result_download, "_resolve", lambda *args: ["8.8.8.8"])
    monkeypatch.setattr(result_download, "_connection", lambda *args: connection)
    monkeypatch.setattr(result_download, "TOTAL_TIMEOUT", 0.03)
    with pytest.raises(ProjectError, match="RESULT_DOWNLOAD_FAILED"):
        result_download.download_image(URL, tmp_path / "image.png")
    assert interrupted.is_set()
    assert not (tmp_path / "image.png").exists()
