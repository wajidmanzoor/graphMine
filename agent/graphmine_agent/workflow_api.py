"""Workflow HTTP routes delegate validation and execution to existing services."""

from fastapi import Query, Request
from starlette.concurrency import run_in_threadpool

from .analytics import GroupMembershipRequest, WorkflowApproval, WorkflowRequest, WorkflowRevision
from .analytics_planning import AnalyticsPlanner, PlanningRequest
from .export_streams import prepare_download


def register_workflow_routes(router):
    @router.get("/analytics/capabilities")
    async def analytics_capabilities(request: Request, refresh: bool = False):
        return await request.app.state.runtime.analytics.capabilities(refresh)

    @router.post("/sessions/{session_id}/workflows", status_code=201)
    async def create_workflow(session_id: str, body: WorkflowRequest, request: Request):
        return await request.app.state.runtime.analytics.create(session_id, body)

    @router.post("/sessions/{session_id}/analytics/plan")
    async def plan_analytics(session_id: str, body: PlanningRequest, request: Request):
        runtime = request.app.state.runtime
        return await AnalyticsPlanner(
            runtime.settings, runtime.analytics, runtime.events
        ).plan(session_id, body)

    @router.post("/sessions/{session_id}/analytics/plan/{turn_id}/cancel")
    async def cancel_planning(session_id: str, turn_id: str, request: Request):
        """Stop a question that is still being planned; nothing has run yet."""
        runtime = request.app.state.runtime
        cancelled = AnalyticsPlanner(
            runtime.settings, runtime.analytics, runtime.events
        ).cancel(session_id, turn_id)
        return {"cancelled": cancelled}

    @router.get("/sessions/{session_id}/workflows")
    def list_workflows(session_id: str, request: Request, summary: bool = False):
        return request.app.state.runtime.analytics.list(session_id, summary=summary)

    @router.get("/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str, request: Request):
        analytics = request.app.state.runtime.analytics
        record = analytics.get(workflow_id)
        return {**record, "queue_position": analytics.queue_position(record)}

    @router.post("/workflows/{workflow_id}/revise")
    async def revise_workflow(
        workflow_id: str, body: WorkflowRevision, request: Request
    ):
        return await request.app.state.runtime.analytics.revise(workflow_id, body)

    @router.post("/workflows/{workflow_id}/run", status_code=202)
    async def run_workflow(workflow_id: str, body: WorkflowApproval, request: Request):
        return await request.app.state.runtime.analytics.start(
            workflow_id, body.workflow_hash, body.expected_revision
        )

    @router.delete("/workflows/{workflow_id}")
    async def cancel_workflow(workflow_id: str, request: Request):
        return await request.app.state.runtime.analytics.cancel(workflow_id)

    @router.get("/workflows/{workflow_id}/result")
    async def workflow_result(
        workflow_id: str, request: Request, summary: bool = False, partial: bool = False,
        expected_revision: int | None = Query(None, ge=1),
    ):
        analytics = request.app.state.runtime.analytics
        if summary:
            return await run_in_threadpool(analytics.result_summary, workflow_id, expected_revision=expected_revision)
        from .analytics_exports import export_json, export_partial_json

        async with analytics.edit_lock:
            return await prepare_download(analytics, export_partial_json if partial else export_json, analytics, workflow_id,
                                          expected_revision=expected_revision, filename="graphmine-result.json", media_type="application/json")

    @router.get("/workflows/{workflow_id}/steps/{step}/result")
    async def workflow_step_result(workflow_id: str, step: str, request: Request, expected_revision: int | None = Query(None, ge=1)):
        from .analytics_exports import export_json

        analytics = request.app.state.runtime.analytics
        async with analytics.edit_lock:
            return await prepare_download(analytics, export_json, analytics, workflow_id, step=step, expected_revision=expected_revision,
                                          filename="graphmine-step-result.json", media_type="application/json")

    @router.get(
        "/workflows/{workflow_id}/steps/{step}/ports/{port}/groups/{index}/graph"
    )
    async def group_graph(
        workflow_id: str, step: str, port: str, index: int, request: Request,
        expected_revision: int | None = Query(None, ge=1),
    ):
        return await run_in_threadpool(
            request.app.state.runtime.analytics.group_graph, workflow_id, step, port, index, expected_revision=expected_revision
        )

    @router.post("/workflows/{workflow_id}/steps/{step}/ports/{port}/memberships")
    async def workflow_memberships(
        workflow_id: str,
        step: str,
        port: str,
        body: GroupMembershipRequest,
        request: Request,
        expected_revision: int | None = Query(None, ge=1),
    ):
        return await run_in_threadpool(
            request.app.state.runtime.analytics.group_memberships,
            workflow_id,
            step,
            port,
            body.vertices,
            expected_revision=expected_revision,
        )

    @router.get("/workflows/{workflow_id}/steps/{step}/ports/{port}")
    async def workflow_port(
        workflow_id: str,
        step: str,
        port: str,
        request: Request,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
        search: str | None = Query(None, max_length=500),
        sort: str | None = Query(None, max_length=200),
        descending: bool = False,
        min_size: int | None = Query(None, ge=0),
        max_size: int | None = Query(None, ge=0),
        member: str | None = Query(None, min_length=1, max_length=500),
        expected_revision: int | None = Query(None, ge=1),
    ):
        return await run_in_threadpool(
            request.app.state.runtime.analytics.port_page,
            workflow_id,
            step,
            port,
            offset,
            limit,
            search,
            sort,
            descending,
            min_size,
            max_size,
            member,
            expected_revision=expected_revision,
        )

