import hashlib
import json
from typing import Any

import pytest
from app.services import bailian_contract as provider
from app.storage.errors import ProjectError


def image_input() -> dict[str, Any]:
    return {
        "mediaId": "00000000-0000-4000-8000-000000000001",
        "bytes": b"verified-image",
        "sha256": hashlib.sha256(b"verified-image").hexdigest(),
        "mime": "image/png",
        "role": "identity",
        "state": "verified",
        "crop": None,
    }


def test_image_compiler_preserves_actual_bytes_order_and_disables_rewrite() -> None:
    request = provider.compile_image(
        "人物站在门边", "字幕", 1024, 1024, [image_input()], count_tokens=lambda text: 20
    )
    body = request["body"]
    assert body["model"] == "qwen-image-2.0-2026-03-03"
    assert body["input"]["messages"][0]["content"][0] == {
        "image": "data:image/png;base64,dmVyaWZpZWQtaW1hZ2U="
    }
    assert body["parameters"] == {
        "n": 1,
        "size": "1024*1024",
        "prompt_extend": False,
        "negative_prompt": "字幕",
        "watermark": False,
    }
    assert request["references"][0]["sha256"] == image_input()["sha256"]
    assert request["maximumMicroCny"] == 200000
    assert request["enabled"] is False


@pytest.mark.parametrize(
    "change", ["missing_counter", "tokens", "references", "role", "hash", "unverified", "crop"]
)
def test_incompatible_image_input_is_rejected_without_silent_loss(change: str) -> None:
    references = [image_input()]

    def count_tokens(text: str) -> int:
        return 1301 if change == "tokens" else 20

    counter = None if change == "missing_counter" else count_tokens
    if change == "references":
        references *= 4
    if change == "role":
        references[0]["role"] = "audioDrive"
    if change == "hash":
        references[0]["sha256"] = "0" * 64
    if change == "unverified":
        references[0]["state"] = "pending"
    if change == "crop":
        references[0]["crop"] = {"x": 0}
    with pytest.raises(ProjectError):
        provider.compile_image("人物", "", 1024, 1024, references, count_tokens=counter)


def test_text_compiler_freezes_json_non_thinking_request_and_upper_price() -> None:
    request = provider.compile_text(
        "输出JSON并保持来源", {"sourceText": "原文"}, 1000, count_tokens=lambda text: 100
    )
    assert request["body"]["enable_thinking"] is False
    assert request["body"]["max_tokens"] == 1000
    assert request["body"]["response_format"] == {"type": "json_object"}
    assert request["maximumMicroCny"] == 1515
    assert request["enabled"] is False


def test_text_decoder_rejects_truncation_and_preserves_raw_at_boundary() -> None:
    raw = {
        "choices": [{"finish_reason": "length", "message": {"content": '{"sourceText":'}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 8},
    }
    with pytest.raises(ProjectError, match="STRUCTURED_RESULT_INVALID"):
        provider.decode_text(raw)
    assert raw["choices"][0]["finish_reason"] == "length"


def test_text_decoder_returns_full_payload_for_strict_candidate_validation() -> None:
    payload = {"kind": "story", "content": {"sourceText": "原文"}}
    raw = {
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 8},
    }
    decoded = provider.decode_text(raw)
    assert decoded["payload"] == payload
    assert decoded["usage"] == {"inputTokens": 4, "outputTokens": 8}


def test_image_decoder_retains_protected_url_but_rejects_missing_result() -> None:
    raw = {
        "output": {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": [
                            {
                                "image": "https://dashscope-result.oss-cn-beijing.aliyuncs.com/image?signature=private"
                            }
                        ]
                    },
                }
            ]
        }
    }
    result = provider.decode_image(raw)
    assert result["resultType"] == "image"
    assert result["synthetic"] is False
    assert result["resultRef"].endswith("signature=private")
    with pytest.raises(ProjectError, match="STRUCTURED_RESULT_INVALID"):
        provider.decode_image({"output": {"choices": []}})


@pytest.mark.parametrize("field", ["keep", "ignore"])
def test_unsupported_reference_instructions_are_not_silently_dropped(field: str) -> None:
    reference = image_input()
    reference[field] = ["round glasses"]
    with pytest.raises(ProjectError, match="INPUT_INCOMPATIBLE"):
        provider.compile_image("人物", "", 1024, 1024, [reference], count_tokens=lambda text: 20)


@pytest.mark.parametrize("width,height", [(2688, 1536), (1536, 2688), (2368, 1728)])
def test_qwen2_resolution_uses_documented_total_pixel_bound(width: int, height: int) -> None:
    request = provider.compile_image("人物", "", width, height, [], count_tokens=lambda text: 20)
    assert request["body"]["parameters"]["size"] == f"{width}*{height}"
