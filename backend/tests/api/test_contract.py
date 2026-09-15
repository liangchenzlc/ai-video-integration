from typing import Any

from app.main import create_app

from tests.api.test_runtime import DESIGN, make_context


def normalized(value: Any, document: dict[str, Any]) -> Any:
    if isinstance(value, list):
        return [normalized(item, document) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        target: Any = document
        for part in value["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return normalized(target, document)
    result = {
        key: normalized(item, document)
        for key, item in value.items()
        if key not in {"title", "description", "example", "examples"}
    }
    for key in ("required", "enum"):
        if key in result and isinstance(result[key], list):
            result[key] = sorted(result[key])
    return result


def test_runtime_openapi_matches_design_structure() -> None:
    actual = create_app(make_context()).openapi()
    assert actual["openapi"] == DESIGN["openapi"]
    assert actual["info"]["version"] == DESIGN["info"]["version"]
    assert actual["security"] == DESIGN["security"]
    assert actual["components"]["securitySchemes"] == DESIGN["components"]["securitySchemes"]
    assert set(actual["paths"]) == set(DESIGN["paths"])
    for path, methods in DESIGN["paths"].items():
        assert set(actual["paths"][path]) == set(methods)
        for method, operation in methods.items():
            generated = actual["paths"][path][method]
            assert generated["operationId"] == operation["operationId"]
            assert normalized(generated["parameters"], actual) == normalized(
                operation["parameters"], DESIGN
            )
            assert set(generated["responses"]) == set(operation["responses"])
            for status, response in operation["responses"].items():
                assert normalized(generated["responses"][status], actual) == normalized(
                    response, DESIGN
                ), (path, status)
