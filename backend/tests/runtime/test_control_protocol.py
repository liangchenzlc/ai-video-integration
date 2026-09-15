import copy
import json
from pathlib import Path

import pytest
from app.runtime.control_protocol import (
    FRAME_LIMIT,
    Direction,
    FrameDecoder,
    FrameEncoder,
    ProtocolError,
    parse_frame,
)

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = json.loads(
    (ROOT / "docs/技术方案/契约/t01-control.examples.json").read_text(encoding="utf-8")
)
IDENTITY = ("22222222-2222-4222-8222-222222222222", 1)


def wire(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


@pytest.mark.parametrize(
    "direction", ["mainToSupervisor", "supervisorToApi", "apiToSupervisor", "supervisorToMain"]
)
@pytest.mark.parametrize("size", [1, 7, 65536])
def test_shared_sequences_roundtrip_across_arbitrary_chunks(
    direction: Direction, size: int
) -> None:
    decoder = FrameDecoder(direction, *IDENTITY)
    encoder = FrameEncoder(direction, *IDENTITY)
    stream = b"".join(
        encoder.encode(frame["type"], frame["payload"]) for frame in EXAMPLES[direction]
    )
    received = []
    for offset in range(0, len(stream), size):
        received.extend(decoder.feed(stream[offset : offset + size]))
    decoder.eof()
    assert [frame.model_dump(by_alias=True) for frame in received] == EXAMPLES[direction]


@pytest.mark.parametrize(
    "mutation",
    [
        "sequence",
        "generation",
        "identity",
        "extra",
        "boolean",
        "fraction",
        "string",
        "version",
        "direction",
        "token",
        "path",
        "snake",
        "surrogate",
        "port",
    ],
)
def test_invalid_frame_mutations_are_rejected_without_echo(mutation: str) -> None:
    frame = copy.deepcopy(EXAMPLES["mainToSupervisor"][0])
    if mutation == "sequence":
        frame["seq"] = 2
    elif mutation == "generation":
        frame["generation"] = 2
    elif mutation == "identity":
        frame["runtimeId"] = "33333333-3333-4333-8333-333333333333"
    elif mutation == "extra":
        frame["secret"] = "SECRET_SENTINEL"
    elif mutation == "boolean":
        frame["generation"] = True
    elif mutation == "fraction":
        frame["generation"] = 1.5
    elif mutation == "string":
        frame["generation"] = "1"
    elif mutation == "version":
        frame["protocolVersion"] = 2
    elif mutation == "direction":
        frame = copy.deepcopy(EXAMPLES["supervisorToMain"][0])
    elif mutation == "token":
        frame["payload"]["tokenB64Url"] = "A" * 42 + "B"
    elif mutation == "path":
        frame["payload"]["appDataDir"] = r"\rooted"
    elif mutation == "snake":
        frame["payload"]["token_b64_url"] = frame["payload"].pop("tokenB64Url")
    elif mutation == "surrogate":
        frame["payload"]["appDataDir"] = "C:\\" + "\ud800"
    elif mutation == "port":
        frame = copy.deepcopy(EXAMPLES["apiToSupervisor"][0])
        frame["payload"]["port"] = 65536
    decoder = FrameDecoder(
        "apiToSupervisor" if mutation == "port" else "mainToSupervisor", *IDENTITY
    )
    raw = json.dumps(frame, ensure_ascii=True).encode() + b"\n"
    with pytest.raises(ProtocolError) as error:
        decoder.feed(raw)
    assert "SECRET_SENTINEL" not in str(error.value)
    assert "tokenB64Url" not in str(error.value)
    with pytest.raises(ProtocolError):
        decoder.feed(wire(EXAMPLES["mainToSupervisor"][0]))


@pytest.mark.parametrize(
    "kind",
    ["duplicate", "escaped_duplicate", "bom", "crlf", "blank", "utf8", "nan", "infinity", "deep"],
)
def test_invalid_json_framing(kind: str) -> None:
    raw = wire(EXAMPLES["mainToSupervisor"][0])
    if kind == "duplicate":
        raw = raw.replace(b'"seq":1', b'"seq":1,"seq":1')
    elif kind == "escaped_duplicate":
        raw = raw.replace(b'"seq":1', b'"seq":1,"s\\u0065q":1')
    elif kind == "bom":
        raw = b"\xef\xbb\xbf" + raw
    elif kind == "crlf":
        raw = raw[:-1] + b"\r\n"
    elif kind == "blank":
        raw = b"\n"
    elif kind == "utf8":
        raw = b"\xff\n"
    elif kind == "nan":
        raw = raw.replace(b'"generation":1', b'"generation":NaN')
    elif kind == "infinity":
        raw = raw.replace(b'"generation":1', b'"generation":Infinity')
    elif kind == "deep":
        raw = b"[" * 1000 + b"0" + b"]" * 1000 + b"\n"
    with pytest.raises(ProtocolError):
        FrameDecoder("mainToSupervisor").feed(raw)


def test_utf8_path_and_exact_frame_size_boundary() -> None:
    frame = copy.deepcopy(EXAMPLES["mainToSupervisor"][0])
    frame["payload"]["appDataDir"] = "C:\\项目 工作区😀"
    raw = wire(frame)
    # JSON whitespace permits exercising 16 KiB without violating field lengths.
    bounded = raw[:-1] + b" " * (FRAME_LIMIT - len(raw)) + b"\n"
    assert len(bounded) == FRAME_LIMIT
    decoder = FrameDecoder("mainToSupervisor")
    frames = []
    for byte in bounded:
        frames.extend(decoder.feed(bytes([byte])))
    assert frames[0].model_dump(by_alias=True) == frame
    with pytest.raises(ProtocolError):
        FrameDecoder("mainToSupervisor").feed(bounded[:-1] + b" \n")


def test_half_frame_eof_and_repeated_init() -> None:
    decoder = FrameDecoder("mainToSupervisor")
    decoder.feed(wire(EXAMPLES["mainToSupervisor"][0])[:-1])
    with pytest.raises(ProtocolError):
        decoder.eof()
    decoder = FrameDecoder("mainToSupervisor")
    decoder.feed(wire(EXAMPLES["mainToSupervisor"][0]))
    second = copy.deepcopy(EXAMPLES["mainToSupervisor"][0])
    second["seq"] = 2
    with pytest.raises(ProtocolError):
        decoder.feed(wire(second))


def test_integer_normalization_and_secret_repr() -> None:
    frame = copy.deepcopy(EXAMPLES["mainToSupervisor"][0])
    frame["generation"] = 1.0
    result = parse_frame(wire(frame)[:-1])
    assert type(result.generation) is int
    assert "tokenB64Url" not in repr(result)
    assert frame["payload"]["tokenB64Url"] not in repr(result)
