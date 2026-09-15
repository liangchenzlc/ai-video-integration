"""Install pinned, checksum-verified portable tools inside this repository."""

import base64
import hashlib
import io
import json
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
BASELINE = json.loads(
    (ROOT / "docs/技术方案/契约/t01-toolchain-baseline.json").read_text(encoding="utf-8")
)


def download(url: str) -> bytes:
    with urlopen(url, timeout=60) as response:
        return response.read()


def write(relative: str, data: bytes) -> None:
    target = (TOOLS / relative).resolve()
    if not target.is_relative_to(TOOLS.resolve()):
        raise ValueError("Archive path escapes tool directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def main() -> None:
    node_version = BASELINE["target"]["node"]
    if not (TOOLS / "node/node.exe").exists():
        filename = f"node-v{node_version}-win-x64.zip"
        base = f"https://nodejs.org/dist/v{node_version}/"
        hashes = download(base + "SHASUMS256.txt").decode("utf-8")
        expected = next(
            line.split()[0] for line in hashes.splitlines() if line.split()[-1] == filename
        )
        data = download(base + filename)
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Node checksum mismatch")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for item in archive.infolist():
                parts = item.filename.split("/", 1)
                if len(parts) == 2 and not item.is_dir():
                    write("node/" + parts[1], archive.read(item))
        print("Node verified and extracted.", flush=True)
    uv_version = BASELINE["tools"]["uv"]
    if not (TOOLS / "uv/uv.exe").exists():
        metadata = json.loads(download(f"https://pypi.org/pypi/uv/{uv_version}/json"))
        wheel = next(x for x in metadata["urls"] if x["filename"].endswith("win_amd64.whl"))
        data = download(wheel["url"])
        if hashlib.sha256(data).hexdigest() != wheel["digests"]["sha256"]:
            raise ValueError("uv checksum mismatch")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            executable = next(n for n in archive.namelist() if n.endswith("/uv.exe"))
            write("uv/uv.exe", archive.read(executable))
        print("uv verified and extracted.", flush=True)
    pnpm_version = BASELINE["tools"]["pnpm"]
    if not (TOOLS / "pnpm/bin/pnpm.cjs").exists():
        metadata = json.loads(download(f"https://registry.npmjs.org/pnpm/{pnpm_version}"))
        data = download(metadata["dist"]["tarball"])
        algorithm, expected = metadata["dist"]["integrity"].split("-", 1)
        if (
            algorithm != "sha512"
            or base64.b64encode(hashlib.sha512(data).digest()).decode() != expected
        ):
            raise ValueError("pnpm checksum mismatch")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member in archive.getmembers():
                if member.isfile():
                    stream = archive.extractfile(member)
                    assert stream is not None
                    write("pnpm/" + member.name.removeprefix("package/"), stream.read())
                elif not member.isdir():
                    raise ValueError("Unsupported archive entry")
        print("pnpm verified and extracted.", flush=True)
    write(
        "bin/pnpm.cmd",
        b'@echo off\r\n"%~dp0..\\node\\node.exe" "%~dp0..\\pnpm\\bin\\pnpm.cjs" %*\r\n',
    )
    environment = os.environ.copy()
    environment["UV_PYTHON_INSTALL_DIR"] = str(TOOLS / "python")
    environment["UV_CACHE_DIR"] = str(ROOT / ".cache/uv")
    subprocess.run(
        [str(TOOLS / "uv/uv.exe"), "python", "install", BASELINE["target"]["python"]],
        env=environment,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    for argv in [
        [str(TOOLS / "node/node.exe"), "--version"],
        [str(TOOLS / "uv/uv.exe"), "--version"],
        [str(TOOLS / "node/node.exe"), str(TOOLS / "pnpm/bin/pnpm.cjs"), "--version"],
    ]:
        subprocess.run(argv, check=True, creationflags=subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    main()
