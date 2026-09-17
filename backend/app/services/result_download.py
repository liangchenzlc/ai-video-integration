"""Bounded HTTPS result retrieval; provider credentials never enter this port."""

import hashlib
import http.client
import ipaddress
import os
import queue
import re
import socket
import ssl
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urljoin, urlsplit

from app.storage.errors import ProjectError
from app.storage.paths import checked_path

TOTAL_TIMEOUT = 60.0
IO_TIMEOUT = 10.0
MAX_REDIRECTS = 3
_HOST = re.compile(r"dashscope-[a-z0-9-]+\.oss-(?:accelerate|cn-[a-z0-9-]+)\.aliyuncs\.com")


def _resolve(host: str, timeout: float) -> list[str]:
    # getaddrinfo has no portable timeout. A daemon keeps a stalled resolver
    # from holding the single task execution slot indefinitely.
    result: queue.Queue[list[str] | Exception] = queue.Queue(maxsize=1)

    def lookup() -> None:
        try:
            result.put(
                list(
                    {
                        str(item[4][0])
                        for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                    }
                )
            )
        except OSError as error:
            result.put(error)

    threading.Thread(target=lookup, daemon=True, name="result-dns").start()
    value = result.get(timeout=timeout)
    if isinstance(value, Exception):
        raise value
    return value


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, timeout: float):
        self.tls_context = ssl.create_default_context()
        super().__init__(host, timeout=timeout, context=self.tls_context)
        self.address = address

    def connect(self) -> None:
        address = ipaddress.ip_address(self.address)
        raw = socket.socket(
            socket.AF_INET6 if address.version == 6 else socket.AF_INET, socket.SOCK_STREAM
        )
        self.sock = raw
        try:
            raw.settimeout(self.timeout)
            raw.connect((self.address, 443))
            # Connect to the checked numeric address; certificate/SNI use the
            # original hostname. No second DNS lookup and no environment proxy.
            self.sock = self.tls_context.wrap_socket(
                raw, server_hostname=self.host, do_handshake_on_connect=False
            )
            self.sock.do_handshake()
        except BaseException:
            raw.close()
            self.close()
            raise


def _connection(host: str, address: str, timeout: float) -> _PinnedHTTPS:
    return _PinnedHTTPS(host, address, timeout)


def _url(url: str) -> SplitResult:
    try:
        if (
            not isinstance(url, str)
            or len(url) > 16384
            or any(ord(c) <= 32 or ord(c) >= 127 for c in url)
        ):
            raise ValueError
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not _HOST.fullmatch(parsed.hostname)
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or "\\" in url
        ):
            raise ValueError
        return parsed
    except ValueError:
        raise ProjectError("RESULT_URL_REJECTED", 422) from None


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProjectError("RESULT_DOWNLOAD_FAILED", 422)
    return min(IO_TIMEOUT, remaining)


def download_image(url: str, target: Path, *, max_bytes: int = 10 * 1024 * 1024) -> dict[str, Any]:
    """Write a new staging file; decoding and atomic publication happen later.

    Return only safe metadata. Never overwrite an existing target, and remove
    only the partial file created by this invocation on failure.
    """
    checked_path(target.parent)
    if type(max_bytes) is not int or not 1 <= max_bytes <= 10 * 1024 * 1024:
        raise ProjectError("RESULT_SIZE_LIMIT", 422)
    deadline = time.monotonic() + TOTAL_TIMEOUT
    created = False
    try:
        for hop in range(MAX_REDIRECTS + 1):
            parsed = _url(url)
            host = parsed.hostname
            assert host is not None
            addresses = _resolve(host, _remaining(deadline))
            if not addresses or any(
                not ipaddress.ip_address(address).is_global
                or ipaddress.ip_address(address).is_multicast
                or getattr(ipaddress.ip_address(address), "ipv4_mapped", None) is not None
                for address in addresses
            ):
                raise ProjectError("RESULT_URL_REJECTED", 422)
            connection = _connection(host, addresses[0], _remaining(deadline))
            transport_sockets: list[socket.socket] = []
            response: http.client.HTTPResponse | None = None

            # A hard wall-clock bound also interrupts a slow header/body peer
            # which supplies bytes just often enough to evade socket timeout.
            def expire(
                current: http.client.HTTPSConnection = connection,
                retained: list[socket.socket] = transport_sockets,
            ) -> None:
                sockets = [*retained, current.sock]
                for sock in sockets:
                    if sock is None:
                        continue
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                current.close()

            timer = threading.Timer(max(0.001, deadline - time.monotonic()), expire)
            timer.daemon = True
            timer.start()
            try:
                connection.request(
                    "GET",
                    parsed.path or "/"
                    if not parsed.query
                    else (parsed.path or "/") + "?" + parsed.query,
                    headers={"Accept": "image/png,image/jpeg", "Accept-Encoding": "identity"},
                )
                # getresponse detaches Connection: close sockets from the
                # connection; retain it so the deadline still interrupts reads.
                if connection.sock is not None:
                    transport_sockets.append(connection.sock)
                response = connection.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if not location or hop == MAX_REDIRECTS:
                        raise ProjectError("RESULT_URL_REJECTED", 422)
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise ProjectError("RESULT_DOWNLOAD_FAILED", 422)
                mime = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
                if (
                    mime not in {"image/png", "image/jpeg"}
                    or response.getheader("Content-Encoding", "identity") != "identity"
                ):
                    raise ProjectError("RESULT_MEDIA_INVALID", 422)
                length_header = response.getheader("Content-Length")
                length = int(length_header) if length_header is not None else None
                if length is not None and not 1 <= length <= max_bytes:
                    raise ProjectError("RESULT_SIZE_LIMIT", 422)
                digest, count = hashlib.sha256(), 0
                with target.open("xb") as output:
                    created = True
                    while True:
                        _remaining(deadline)
                        chunk = response.read1(min(65536, max_bytes + 1 - count))
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > max_bytes:
                            raise ProjectError("RESULT_SIZE_LIMIT", 422)
                        digest.update(chunk)
                        output.write(chunk)
                    if count == 0 or (length is not None and count != length):
                        raise ProjectError("RESULT_MEDIA_INVALID", 422)
                    output.flush()
                    os.fsync(output.fileno())
                _remaining(deadline)
                return {"mime": mime, "byteLength": count, "sha256": digest.hexdigest()}
            finally:
                timer.cancel()
                if response is not None:
                    response.close()
                connection.close()
        raise ProjectError("RESULT_URL_REJECTED", 422)
    except BaseException as error:
        if created:
            target.unlink(missing_ok=True)
        if isinstance(error, ProjectError):
            raise
        if isinstance(error, (OSError, ValueError, http.client.HTTPException, queue.Empty)):
            raise ProjectError("RESULT_DOWNLOAD_FAILED", 422) from None
        raise
