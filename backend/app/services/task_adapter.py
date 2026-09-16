"""Explicit local synthetic port. No network client or real billing capability is registered."""

from typing import Any

from app.storage.task_plans import CAPABILITY_ID


class SyntheticAdapter:
    @staticmethod
    def _payload(request: dict[str, Any]) -> dict[str, Any]:
        kind = request["inputPreview"]["kind"]
        content = dict(request["inputPreview"]["payload"])
        if kind == "story":
            content.setdefault("inputType", "idea")
            content.setdefault("approvalLevel", "proposal")
            content.setdefault("outline", [])
            content.setdefault("requirements", [])
            content.setdefault("scenes", [])
            content.setdefault("dialogues", [])
            content.setdefault("adaptationNotes", [])
        return {"kind": kind, "content": content}

    @classmethod
    def _result(cls, request: dict[str, Any]) -> dict[str, Any]:
        if (
            request["step"]["purpose"] == "create"
            and request.get("stage") == "image"
            and request["inputPreview"]["kind"] in {"asset", "shot"}
        ):
            return {
                "provenance": "synthetic",
                "resultProtocolVersion": "candidate-v1",
                "resultType": "image",
                "synthetic": True,
            }
        if request.get("stage") == "story":
            return {
                "provenance": "synthetic",
                "resultProtocolVersion": "candidate-v1",
                "payload": cls._payload(request),
            }
        return {
            "provenance": "synthetic",
            "kind": request["inputPreview"]["kind"],
            "payload": request["inputPreview"]["payload"],
        }

    def describe(self, phase: str) -> dict[str, Any]:
        return {
            "id": CAPABILITY_ID,
            "providerId": "synthetic-local",
            "modelId": "fixture-v1",
            "region": "local",
            "version": "synthetic-v1",
            "priceVersion": "synthetic-price-v1",
            "maxReferences": 2,
            "durationOptionsMs": [5000, 10000] if phase == "video" else [],
            "supportsQuery": True,
            "supportsCancel": False,
        }

    def estimate(self, phase: str, requested_ms: int | None, purpose: str) -> int:
        return 1_200_000 if phase == "video" else 100_000

    def prepare(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return snapshot

    def submit(self, request: dict[str, Any], submission_token: str) -> dict[str, Any]:
        return {
            "remoteTaskId": "synthetic-" + submission_token,
            "result": self._result(request),
        }

    def query(self, remote_task_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return {"remoteTaskId": remote_task_id, "result": self._result(request)}

    def download(self, result: dict[str, Any]) -> dict[str, Any]:
        return result
