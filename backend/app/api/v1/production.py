"""Production workspace index and explicitly requested local diagnostics."""

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, JsonValue

from app.api.v1.models import Uuid
from app.api.v1.projects import ProjectStore, project_session, window_identity
from app.api.v1.projects_models import BusinessModel, Command, Envelope, MutationReceipt
from app.storage import issues


class DiagnosticOptions(BusinessModel):
    project_id: Uuid | None
    include_project: bool
    include_content: bool


class DiagnosticPayload(DiagnosticOptions):
    target_grant_id: Uuid


class DiagnosticFile(BusinessModel):
    name: str
    description: str


class DiagnosticPreview(DiagnosticOptions):
    files: list[DiagnosticFile]


class DraftSummary(BusinessModel):
    id: Uuid
    artifact_id: Uuid
    kind: Literal["story", "asset", "shot", "speech", "subtitle", "timeline", "observation"]
    saved_at: str


class AdoptedSummary(BusinessModel):
    artifact_id: Uuid
    revision_id: Uuid
    kind: Literal["story", "asset", "shot", "speech", "subtitle", "timeline", "observation"]
    confirmed: bool
    needs_update: bool
    content: dict[str, JsonValue]


class ProductionIndex(BusinessModel):
    drafts: list[DraftSummary] = Field(max_length=5000)
    adopted: list[AdoptedSummary] = Field(max_length=5000)
    next_offset: int | None


class Issue(BusinessModel):
    id: Uuid
    rule_id: str
    rule_version: str
    artifact_id: Uuid
    revision_id: Uuid
    baseline_revision_id: Uuid | None
    severity: Literal["blocking", "unknown_required", "deviation", "advice"]
    status: Literal["open", "fixing", "recheck", "resolved", "accepted_deviation"]
    message: str
    evidence: str
    time: dict[str, int] | None
    method: Literal["local", "ai", "human"]
    limitations: str


class IssuePage(BusinessModel):
    items: list[Issue]
    next_cursor: Uuid | None


class IssueDecision(BusinessModel):
    action: Literal["accept_deviation", "request_recheck", "attach_evidence"]
    reason: str = Field(min_length=1, max_length=2000)
    evidence_media_ids: list[Uuid] = Field(max_length=1000)


def production_router(store: ProjectStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Production workspace and T13 diagnostics"])

    @router.get("/projects/{project_id}/issues", response_model=Envelope[IssuePage])
    def list_issues(
        project_id: Uuid,
        request: Request,
        cursor: Uuid | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        window: int = Depends(window_identity),
    ) -> Any:
        owner = store.get()
        with owner._mutex:
            data = owner._versions.read(
                project_id,
                project_session(request),
                window,
                lambda db, _: issues.page(db, cursor, limit),
            )
        return {"requestId": request.state.request_id, "data": data}

    @router.post(
        "/projects/{project_id}/issues/{issue_id}/decisions",
        response_model=Envelope[MutationReceipt],
    )
    def decision(
        project_id: Uuid,
        issue_id: Uuid,
        command: Command[IssueDecision],
        request: Request,
        window: int = Depends(window_identity),
    ) -> Any:
        owner = store.get()
        with owner._mutex:
            data = owner._versions.write(
                project_id,
                project_session(request),
                window,
                command.model_dump(by_alias=True),
                "decideIssue",
                {"action", "reason", "evidenceMediaIds"},
                issue_id,
                lambda db, _, payload: issues.decide(
                    db, issue_id, payload, command.client_operation_id
                ),
            )
        return {"requestId": request.state.request_id, "data": data}

    @router.get("/projects/{project_id}/production", response_model=Envelope[ProductionIndex])
    def index(
        project_id: Uuid,
        request: Request,
        offset: int = Query(default=0, ge=0),
        window: int = Depends(window_identity),
    ) -> Any:
        owner = store.get()

        def read(db: Any, _: Any) -> Any:
            entries = db.execute(
                "SELECT 'draft' AS category,id FROM drafts UNION ALL "
                "SELECT 'adopted',id FROM artifacts WHERE adopted_revision_id IS NOT NULL "
                "ORDER BY category,id LIMIT 101 OFFSET ?",
                (offset,),
            ).fetchall()
            draft_ids = {r["id"] for r in entries if r["category"] == "draft"}
            artifact_ids = {r["id"] for r in entries if r["category"] == "adopted"}
            drafts = [
                {
                    "id": r["id"],
                    "artifactId": r["artifact_id"],
                    "kind": r["kind"],
                    "savedAt": r["saved_at"],
                }
                for r in db.execute(
                    f"SELECT * FROM drafts WHERE id IN ({','.join('?' for _ in draft_ids)})",
                    tuple(draft_ids),
                )
            ]
            adopted = [
                {
                    "artifactId": r["artifact_id"],
                    "revisionId": r["id"],
                    "kind": r["kind"],
                    "confirmed": r["confirmed_revision_id"] == r["id"],
                    "needsUpdate": bool(r["needs_update"]),
                    "content": json.loads(r["payload_json"])["content"],
                }
                for r in db.execute(
                    "SELECT a.kind,a.confirmed_revision_id,a.needs_update,r.* FROM artifacts a "
                    "JOIN revisions r ON r.id=a.adopted_revision_id "
                    f"WHERE a.id IN ({','.join('?' for _ in artifact_ids)})",
                    tuple(artifact_ids),
                )
            ]
            lookup = {("draft", r["id"]): r for r in drafts}
            lookup.update({("adopted", r["artifactId"]): r for r in adopted})
            page: dict[str, Any] = {"drafts": [], "adopted": [], "nextOffset": None}
            size = 100
            consumed = 0
            for entry in entries[:100]:
                item = lookup[(entry["category"], entry["id"])]
                item_size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
                if consumed and size + item_size > 900 * 1024:
                    break
                page["drafts" if entry["category"] == "draft" else "adopted"].append(item)
                size += item_size
                consumed += 1
            if consumed < len(entries):
                page["nextOffset"] = offset + consumed
            return page

        with owner._mutex:
            data = owner._versions.read(project_id, project_session(request), window, read)
        return {"requestId": request.state.request_id, "data": data}

    @router.post("/diagnostics/preview", response_model=Envelope[DiagnosticPreview])
    def preview(
        payload: DiagnosticOptions, request: Request, window: int = Depends(window_identity)
    ) -> Any:
        return {
            "requestId": request.state.request_id,
            "data": store.get()._diagnostics.preview(
                window,
                payload.model_dump(by_alias=True),
                project_session(request) if payload.include_project else None,
            ),
        }

    @router.post("/diagnostics", status_code=202, response_model=Envelope[MutationReceipt])
    def diagnostic(
        command: Command[DiagnosticPayload],
        request: Request,
        window: int = Depends(window_identity),
    ) -> Any:
        return {
            "requestId": request.state.request_id,
            "data": store.get()._diagnostics.create(
                window,
                command.model_dump(by_alias=True),
                project_session(request) if command.payload.include_project else None,
            ),
        }

    return router
