"""Extract the reachable draft schema from the reviewed domain contract."""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "backend/app/schemas/draft.schema.json"


def draft_schema(root: str = "DraftPayload") -> dict[str, Any]:
    domain = json.loads(
        next((ROOT / "docs").rglob("domain.schema.json")).read_text(encoding="utf-8")
    )
    definitions: dict[str, Any] = {}

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            ref = value.get("$ref", "")
            if ref.startswith("#/$defs/"):
                name = ref.removeprefix("#/$defs/")
                if name not in definitions:
                    definitions[name] = domain["$defs"][name]
                    collect(definitions[name])
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect({"$ref": "#/$defs/" + root})
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": "#/$defs/" + root,
        "$defs": definitions,
    }


if __name__ == "__main__":
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(draft_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    TARGET.with_name("revision.schema.json").write_text(
        json.dumps(draft_schema("TypedPayload"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
