"""Public wire cases consumed by both languages; no implementation imports."""

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    examples = json.loads(
        (ROOT / "docs/技术方案/契约/t01-control.examples.json").read_text(encoding="utf-8")
    )
    vectors = []

    def wire(frame: object) -> bytes:
        return json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"

    def add(name: str, direction: str, raw: bytes, expected: object = None, chunk: int = 7) -> None:
        vectors.append(
            {
                "name": name,
                "direction": direction,
                "wireHex": raw.hex(),
                "chunkSize": chunk,
                "expected": expected,
            }
        )

    for direction in ("mainToSupervisor", "supervisorToApi", "apiToSupervisor", "supervisorToMain"):
        for size in (1, 7, 65536):
            add(
                f"{direction}-chunks-{size}",
                direction,
                b"".join(wire(frame) for frame in examples[direction]),
                examples[direction],
                size,
            )
    init = examples["mainToSupervisor"][0]
    raw = wire(init)
    malformed = {
        "duplicate": raw.replace(b'"seq":1', b'"seq":1,"seq":1'),
        "escaped-duplicate": raw.replace(b'"seq":1', b'"seq":1,"s\\u0065q":1'),
        "nested-duplicate": raw.replace(
            b'"mode":"development"', b'"mode":"development","mode":"development"'
        ),
        "bom": b"\xef\xbb\xbf" + raw,
        "crlf": raw[:-1] + b"\r\n",
        "invalid-utf8": b"\xff\n",
        "blank": b"\n",
        "half-eof": raw[:-1],
        "nan": raw.replace(b'"generation":1', b'"generation":NaN'),
        "infinity": raw.replace(b'"generation":1', b'"generation":Infinity'),
        "deep-json": b"[" * 1000 + b"0" + b"]" * 1000 + b"\n",
    }
    for name, content in malformed.items():
        add(name, "mainToSupervisor", content)
    mutations = {
        "seq": 2,
        "generation": True,
        "protocolVersion": 2,
        "runtimeId": "33333333-3333-4333-8333-333333333333",
        "unexpected": "SECRET_SENTINEL",
    }
    for key, value in mutations.items():
        frame = copy.deepcopy(init)
        frame[key] = value
        add("invalid-" + key, "mainToSupervisor", wire(frame))
    for name, key, value in (
        ("noncanonical-token", "tokenB64Url", "A" * 42 + "B"),
        ("drive-relative", "appDataDir", "C:relative"),
        ("root-relative", "appDataDir", "\\rooted"),
        ("protocol-bool", "expectedApiVersion", True),
    ):
        frame = copy.deepcopy(init)
        frame["payload"][key] = value
        add(name, "mainToSupervisor", wire(frame))
    frame = copy.deepcopy(init)
    frame["payload"]["appDataDir"] = "C:\\工作 区😀"
    raw = wire(frame)
    add("unicode-path", "mainToSupervisor", raw, [frame], 1)
    bounded = raw[:-1] + b" " * (16384 - len(raw)) + b"\n"
    add("maximum-frame", "mainToSupervisor", bounded, [frame], 16384)
    add("oversized-frame", "mainToSupervisor", bounded[:-1] + b" \n", chunk=65536)
    frame = copy.deepcopy(init)
    frame["generation"] = 1.0
    add("integer-normalization", "mainToSupervisor", wire(frame), [init])
    frame = copy.deepcopy(init)
    frame["payload"]["appDataDir"] = "C:\\" + "\ud800"
    add("unpaired-surrogate", "mainToSupervisor", json.dumps(frame).encode() + b"\n")
    frame = copy.deepcopy(init)
    frame["seq"] = 2
    add("repeated-init", "mainToSupervisor", wire(init) + wire(frame))
    add("wrong-direction", "mainToSupervisor", wire(examples["supervisorToMain"][0]))
    path = ROOT / "contracts/control-vectors.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"purpose": "Public test data; never production token defaults.", "vectors": vectors},
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Generated {len(vectors)} shared wire vectors")


if __name__ == "__main__":
    main()
