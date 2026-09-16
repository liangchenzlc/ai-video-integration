"""Explicit local synthetic port. No network client or real billing capability is registered."""

from typing import Any

from app.storage.task_plans import CAPABILITY_ID


class SyntheticAdapter:
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
            "result": {
                "provenance": "synthetic",
                "kind": request["inputPreview"]["kind"],
                "payload": request["inputPreview"]["payload"],
            },
        }

    def query(self, remote_task_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "remoteTaskId": remote_task_id,
            "result": {
                "provenance": "synthetic",
                "kind": request["inputPreview"]["kind"],
                "payload": request["inputPreview"]["payload"],
            },
        }

    def download(self, result: dict[str, Any]) -> dict[str, Any]:
        return result
