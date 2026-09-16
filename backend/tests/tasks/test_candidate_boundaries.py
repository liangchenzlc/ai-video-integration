"""Cross-boundary result invariants, including Unicode and byte-budget paging."""

import hashlib
from uuid import uuid4

import pytest
from app.services.task_adapter import SyntheticAdapter
from tests.storage.test_task_plans import budget, invoke, plan
from tests.tasks.test_candidates import ResultAdapter
from tests.tasks.test_executor import start, wait_task


@pytest.mark.parametrize("end,expected", [(2, "complete"), (4, "failed")])
def test_source_spans_use_unicode_codepoints_not_utf16_offsets(opened, end, expected):
    service, _, session = opened

    def with_span(result):
        content = result["payload"]["content"]
        content["requirements"] = [
            {
                "id": str(uuid4()),
                "text": "保留笑脸",
                "category": "fact",
                "required": True,
                "decision": "keep",
                "decisionReason": "",
                "source": {
                    "sourceHash": content["sourceHash"],
                    "startCodePoint": 1,
                    "endCodePoint": end,
                },
            }
        ]
        return result

    service._tasks.adapter = ResultAdapter(with_span)
    budget(service, session)
    frozen, _ = plan(service, session, content={"sourceText": "甲😀乙", "brief": "保持原文"})
    receipt, _ = start(service, session, frozen)
    task = wait_task(service, session, receipt["resourceId"])
    assert task["state"] == expected
    assert len(task["candidateRevisionIds"]) == (1 if expected == "complete" else 0)


def test_valid_hash_for_changed_source_does_not_authorize_rewriting_input(opened):
    service, _, session = opened

    def change_source(result):
        content = result["payload"]["content"]
        content["sourceText"] = "changed"
        content["sourceHash"] = hashlib.sha256(b"changed").hexdigest()
        return result

    service._tasks.adapter = ResultAdapter(change_source)
    budget(service, session)
    frozen, _ = plan(service, session)
    receipt, _ = start(service, session, frozen)
    assert wait_task(service, session, receipt["resourceId"])["state"] == "failed"


def test_partial_invalid_result_preserves_first_candidate_and_stops_unsubmitted_calls(opened):
    service, _, session = opened

    class Partial(SyntheticAdapter):
        submits = 0

        def submit(self, request, token):
            self.submits += 1
            result = super().submit(request, token)
            if self.submits == 2:
                result["result"].pop("resultProtocolVersion")
            return result

    adapter = Partial()
    service._tasks.adapter = adapter
    budget(service, session)
    frozen, _ = plan(service, session, candidates=3)
    receipt, _ = start(service, session, frozen)
    task = wait_task(service, session, receipt["resourceId"])
    assert task["state"] == "partial"
    assert len(task["candidateRevisionIds"]) == 1
    assert adapter.submits == 2
    assert len(task["callIds"]) == 2
    assert invoke(service, session, "get_cost_summary")["reservedMicroCny"] == 200000


def test_candidate_page_obeys_byte_budget_and_cursor_keeps_every_result(opened):
    service, _, session = opened
    budget(service, session)
    frozen, _ = plan(
        service, session, candidates=3, content={"sourceText": "😀" * 100000, "brief": "保持原文"}
    )
    receipt, _ = start(service, session, frozen)
    task = wait_task(service, session, receipt["resourceId"])
    assert task["state"] == "complete"
    first = invoke(service, session, "list_task_candidates", task["id"], None, 50)
    assert len(first["items"]) == 2
    assert first["nextCursor"] is not None
    second = invoke(service, session, "list_task_candidates", task["id"], first["nextCursor"], 50)
    assert len(second["items"]) == 1
    assert second["nextCursor"] is None
    assert {item["id"] for item in first["items"] + second["items"]} == set(
        task["candidateRevisionIds"]
    )
