import json
from pathlib import Path

import pytest
from app.runtime.control_protocol import FrameDecoder, ProtocolError

ROOT = Path(__file__).resolve().parents[3]
VECTORS = json.loads((ROOT / "contracts/control-vectors.json").read_text(encoding="utf-8"))[
    "vectors"
]


@pytest.mark.parametrize("vector", VECTORS, ids=[item["name"] for item in VECTORS])
def test_shared_wire_vectors(vector: dict) -> None:
    decoder = FrameDecoder(vector["direction"], "22222222-2222-4222-8222-222222222222", 1)
    raw = bytes.fromhex(vector["wireHex"])

    def decode() -> list[dict]:
        frames = []
        for offset in range(0, len(raw), vector["chunkSize"]):
            frames.extend(decoder.feed(raw[offset : offset + vector["chunkSize"]]))
        decoder.eof()
        return [frame.model_dump(by_alias=True) for frame in frames]

    if vector["expected"] is None:
        with pytest.raises(ProtocolError):
            decode()
        with pytest.raises(ProtocolError):
            decoder.feed(b"\n")
    else:
        assert decode() == vector["expected"]
