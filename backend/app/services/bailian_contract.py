"""Offline Beijing request/response contract. No live capability is enabled."""

import base64
import hashlib
import json
from collections.abc import Callable
from typing import Any

from app.storage.errors import ProjectError
from app.storage.settings import canonical
from app.storage.task_plans import identifier

VERSION = "bailian-beijing-2026-09-16"
PRICE_SOURCE = "https://help.aliyun.com/zh/model-studio/model-pricing"
_ROLES = {"identity": "身份", "location": "场景", "prop": "道具", "keyMoment": "关键瞬间"}


def _tokens(text: str, counter: Callable[[str], int] | None, maximum: int) -> int:
    # No character-count approximation may silently become a billing bound.
    # Production registration stays disabled until an exact tokenizer is verified.
    if counter is None:
        raise ProjectError("CAPABILITY_MISSING", 422)
    count = counter(text)
    if type(count) is not int or not 1 <= count <= maximum:
        raise ProjectError("INPUT_SIZE_LIMIT", 422)
    return count


def _prepared(body: dict[str, Any], path: str, maximum: int) -> dict[str, Any]:
    return {
        "enabled": False,
        "region": "cn-beijing",
        "capabilityVersion": VERSION,
        "templateVersion": VERSION,
        "priceVersion": VERSION,
        "priceSource": PRICE_SOURCE,
        "endpoint": "https://dashscope.aliyuncs.com" + path,
        "body": body,
        "requestHash": hashlib.sha256(canonical(body).encode()).hexdigest(),
        "maximumMicroCny": maximum,
    }


def compile_image(
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    references: list[dict[str, Any]],
    *,
    count_tokens: Callable[[str], int] | None = None,
) -> dict[str, Any]:
    """Compile one image per call, from already decoded/verified local media.

    Unsupported crops/purposes fail closed; bytes/order/hashes are frozen in the
    returned protected request, which must never be passed to the renderer.
    """
    if (
        not prompt.strip()
        or len(negative_prompt) > 500
        or len(references) > 3
        or type(width) is not int
        or type(height) is not int
        or width < 16
        or height < 16
        or not 512 * 512 <= width * height <= 2048 * 2048
        or width % 16
        or height % 16
    ):
        raise ProjectError("INPUT_INCOMPATIBLE", 422)
    content: list[dict[str, Any]] = []
    frozen: list[dict[str, Any]] = []
    roles: list[str] = []
    for index, reference in enumerate(references):
        try:
            data = reference["bytes"]
            if (
                not isinstance(data, bytes)
                or not 1 <= len(data) <= 10 * 1024 * 1024
                or reference["mime"] not in {"image/png", "image/jpeg"}
                or reference["state"] != "verified"
                or reference["crop"] is not None
                or reference.get("keep", []) != []
                or reference.get("ignore", []) != []
                or reference["role"] not in _ROLES
                or hashlib.sha256(data).hexdigest() != reference["sha256"]
            ):
                raise ValueError
            identifier(reference["mediaId"])
            content.append(
                {
                    "image": "data:"
                    + reference["mime"]
                    + ";base64,"
                    + base64.b64encode(data).decode("ascii")
                }
            )
            frozen.append({key: reference[key] for key in ("mediaId", "sha256", "mime", "role")})
            frozen[-1]["order"] = index
            roles.append(f"图{index + 1}用于{_ROLES[reference['role']]}参考。")
        except (ValueError, TypeError, KeyError):
            raise ProjectError("INPUT_INCOMPATIBLE", 422) from None
    compiled_prompt = "".join(roles) + prompt
    count = _tokens(compiled_prompt, count_tokens, 1300)
    content.append({"text": compiled_prompt})
    body = {
        "model": "qwen-image-2.0-2026-03-03",
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": {
            "n": 1,
            "size": f"{width}*{height}",
            "negative_prompt": negative_prompt,
            "prompt_extend": False,
            "watermark": False,
        },
    }
    result = _prepared(body, "/api/v1/services/aigc/multimodal-generation/generation", 200_000)
    result.update(references=frozen, inputTokens=count, requestedCandidates=1)
    return result


def compile_text(
    instruction: str,
    frozen_input: dict[str, Any],
    max_output_tokens: int,
    *,
    count_tokens: Callable[[str], int] | None = None,
) -> dict[str, Any]:
    if (
        not instruction.strip()
        or type(max_output_tokens) is not int
        or not 1 <= max_output_tokens <= 8192
    ):
        raise ProjectError("INPUT_INCOMPATIBLE", 422)
    messages = [
        {
            "role": "system",
            "content": instruction + "\n只输出完整 JSON 对象，保持冻结来源和非目标阶段字段。",
        },
        {"role": "user", "content": canonical(frozen_input)},
    ]
    count = _tokens(canonical({"messages": messages}), count_tokens, 128_000)
    body = {
        "model": "qwen-flash-2025-07-28",
        "messages": messages,
        "enable_thinking": False,
        "max_tokens": max_output_tokens,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    # 0.15 / 1.5 CNY per million tokens, rounded upward to integer micro-CNY.
    maximum = (count * 15 + max_output_tokens * 150 + 99) // 100
    result = _prepared(body, "/compatible-mode/v1/chat/completions", maximum)
    result.update(inputTokens=count, maximumOutputTokens=max_output_tokens)
    return result


def decode_text(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        if len(canonical(raw).encode()) > 1024 * 1024 or len(raw["choices"]) != 1:
            raise ValueError
        choice = raw["choices"][0]
        if choice["finish_reason"] != "stop":
            raise ValueError
        payload = json.loads(choice["message"]["content"])
        if not isinstance(payload, dict):
            raise ValueError
        usage = raw["usage"]
        if any(
            type(usage[key]) is not int or not 0 <= usage[key] <= 9007199254740991
            for key in ("prompt_tokens", "completion_tokens")
        ):
            raise ValueError
        return {
            "resultProtocolVersion": "candidate-v1",
            "payload": payload,
            "usage": {
                "inputTokens": usage["prompt_tokens"],
                "outputTokens": usage["completion_tokens"],
            },
        }
    except (KeyError, TypeError, ValueError):
        raise ProjectError("STRUCTURED_RESULT_INVALID", 422) from None


def decode_image(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        if len(canonical(raw).encode()) > 1024 * 1024:
            raise ValueError
        choices = raw["output"]["choices"]
        if len(choices) != 1 or choices[0]["finish_reason"] != "stop":
            raise ValueError
        content = choices[0]["message"]["content"]
        if len(content) != 1 or set(content[0]) != {"image"}:
            raise ValueError
        url = content[0]["image"]
        if not isinstance(url, str) or not 1 <= len(url) <= 16384:
            raise ValueError
        # URL remains protected. The production downloader validates each hop.
        return {
            "resultProtocolVersion": "candidate-v1",
            "resultType": "image",
            "synthetic": False,
            "resultRef": url,
        }
    except (KeyError, IndexError, TypeError, ValueError):
        raise ProjectError("STRUCTURED_RESULT_INVALID", 422) from None
