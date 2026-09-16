"""Finite budgeted task routes. Only the persistent executor can invoke providers."""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.models import Uuid
from app.api.v1.projects import ProjectStore, project_session, window_identity
from app.api.v1.projects_models import Command, Envelope, MutationReceipt
from app.api.v1.tasks_models import (
    Budget,
    Call,
    ContinueTask,
    CostEntryPage,
    CostSummary,
    ExternalExpense,
    PlanTask,
    RecoverCall,
    SetBudget,
    SettleCall,
    StartTask,
    Task,
    TaskActivity,
    TaskPage,
    TaskPlan,
)
from app.api.v1.versions_models import RevisionPage


def tasks_router(store: ProjectStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["T04 tasks"])

    def result(request: Request, data: Any) -> dict[str, Any]:
        return {"requestId": request.state.request_id, "data": data}

    @router.get(
        "/projects/{project_id}/budget", operation_id="getBudget", response_model=Envelope[Budget]
    )
    def get_budget(
        project_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(request, store.get().get_budget(project_id, project_session(request), window))

    @router.put(
        "/projects/{project_id}/budget",
        operation_id="setBudget",
        response_model=Envelope[MutationReceipt],
    )
    def set_budget(
        project_id: Uuid,
        request: Request,
        command: Command[SetBudget],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().set_budget(
                project_id, project_session(request), window, command.model_dump(by_alias=True)
            ),
        )

    @router.post(
        "/projects/{project_id}/task-plans",
        operation_id="planTask",
        response_model=Envelope[MutationReceipt],
    )
    def plan_task(
        project_id: Uuid,
        request: Request,
        command: Command[PlanTask],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().plan_task(
                project_id, project_session(request), window, command.model_dump(by_alias=True)
            ),
        )

    @router.get(
        "/projects/{project_id}/task-plans/{plan_id}",
        operation_id="getTaskPlan",
        response_model=Envelope[TaskPlan],
    )
    def get_task_plan(
        project_id: Uuid, request: Request, plan_id: Uuid, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().get_task_plan(project_id, project_session(request), window, plan_id),
        )

    @router.post(
        "/projects/{project_id}/tasks",
        operation_id="startTask",
        response_model=Envelope[MutationReceipt],
        status_code=202,
    )
    def start_task(
        project_id: Uuid,
        request: Request,
        command: Command[StartTask],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().start_task(
                project_id, project_session(request), window, command.model_dump(by_alias=True)
            ),
        )

    @router.get(
        "/projects/{project_id}/tasks", operation_id="listTasks", response_model=Envelope[TaskPage]
    )
    def list_tasks(
        project_id: Uuid,
        request: Request,
        cursor: Uuid | None = None,
        limit: int = Query(50, ge=1, le=200),
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().list_tasks(
                project_id, project_session(request), window, cursor=cursor, limit=limit
            ),
        )

    @router.get(
        "/projects/{project_id}/tasks/{task_id}",
        operation_id="getTask",
        response_model=Envelope[Task],
    )
    def get_task(
        project_id: Uuid, request: Request, task_id: Uuid, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request, store.get().get_task(project_id, project_session(request), window, task_id)
        )

    @router.get(
        "/projects/{project_id}/tasks/{task_id}/candidates",
        operation_id="listTaskCandidates",
        response_model=Envelope[RevisionPage],
    )
    def list_task_candidates(
        project_id: Uuid,
        request: Request,
        task_id: Uuid,
        cursor: Uuid | None = None,
        limit: int = Query(50, ge=1, le=200),
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().list_task_candidates(
                project_id,
                project_session(request),
                window,
                task_id,
                cursor,
                limit,
            ),
        )

    @router.get(
        "/projects/{project_id}/calls/{call_id}",
        operation_id="getCall",
        response_model=Envelope[Call],
    )
    def get_call(
        project_id: Uuid, request: Request, call_id: Uuid, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request, store.get().get_call(project_id, project_session(request), window, call_id)
        )

    @router.post(
        "/projects/{project_id}/calls/{call_id}/recovery",
        operation_id="recoverCall",
        response_model=Envelope[MutationReceipt],
        status_code=202,
    )
    def recover_call(
        project_id: Uuid,
        request: Request,
        call_id: Uuid,
        command: Command[RecoverCall],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().recover_call(
                project_id,
                project_session(request),
                window,
                call_id,
                command.model_dump(by_alias=True),
            ),
        )

    @router.post(
        "/projects/{project_id}/tasks/{task_id}/continue",
        operation_id="continuePreparedTask",
        response_model=Envelope[MutationReceipt],
        status_code=202,
    )
    def continue_task(
        project_id: Uuid,
        request: Request,
        task_id: Uuid,
        command: Command[ContinueTask],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().continue_task(
                project_id,
                project_session(request),
                window,
                task_id,
                command.model_dump(by_alias=True),
            ),
        )

    @router.get(
        "/projects/{project_id}/cost-summary",
        operation_id="getCostSummary",
        response_model=Envelope[CostSummary],
    )
    def get_cost_summary(
        project_id: Uuid, request: Request, window: int = Depends(window_identity)
    ) -> dict[str, Any]:
        return result(
            request, store.get().get_cost_summary(project_id, project_session(request), window)
        )

    @router.get(
        "/projects/{project_id}/cost-entries",
        operation_id="listCostEntries",
        response_model=Envelope[CostEntryPage],
    )
    def list_cost_entries(
        project_id: Uuid,
        request: Request,
        cursor: Uuid | None = None,
        limit: int = Query(50, ge=1, le=200),
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().list_cost_entries(
                project_id, project_session(request), window, cursor=cursor, limit=limit
            ),
        )

    @router.post(
        "/projects/{project_id}/calls/{call_id}/settlements",
        operation_id="settleCall",
        response_model=Envelope[MutationReceipt],
    )
    def settle_call(
        project_id: Uuid,
        request: Request,
        call_id: Uuid,
        command: Command[SettleCall],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().settle_call(
                project_id,
                project_session(request),
                window,
                call_id,
                command.model_dump(by_alias=True),
            ),
        )

    @router.put(
        "/projects/{project_id}/external-expenses/{expense_id}",
        operation_id="setExternalExpense",
        response_model=Envelope[MutationReceipt],
    )
    def set_external_expense(
        project_id: Uuid,
        request: Request,
        expense_id: Uuid,
        command: Command[ExternalExpense],
        window: int = Depends(window_identity),
    ) -> dict[str, Any]:
        return result(
            request,
            store.get().set_external_expense(
                project_id,
                project_session(request),
                window,
                expense_id,
                command.model_dump(by_alias=True),
            ),
        )

    @router.get(
        "/task-activity",
        operation_id="getTaskActivity",
        response_model=Envelope[list[TaskActivity]],
    )
    def activity(request: Request, window: int = Depends(window_identity)) -> dict[str, Any]:
        return result(request, store.get().get_task_activity())

    return router
