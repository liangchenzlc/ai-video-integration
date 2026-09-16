import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from jsonschema import Draft202012Validator


def test_runtime_draft_schema_matches_design_and_allows_partial_text() -> None:
    root = Path(__file__).resolve().parents[3]
    spec = spec_from_file_location(
        "draft_schema_builder", root / "backend/scripts/build_draft_schema.py"
    )
    assert spec and spec.loader
    builder = module_from_spec(spec)
    spec.loader.exec_module(builder)
    actual = json.loads(
        (root / "backend/app/schemas/draft.schema.json").read_text(encoding="utf-8")
    )
    assert actual == builder.draft_schema()
    validator = Draft202012Validator(actual)
    for content in ({}, {"sourceText": ""}, {"sourceText": "未完成", "brief": ""}):
        validator.validate({"kind": "story", "content": content})
    assert not validator.is_valid({"kind": "story", "content": {"inputType": "invalid"}})
    assert not validator.is_valid({"kind": "story", "content": {"sourceText": "a" * 100001}})
