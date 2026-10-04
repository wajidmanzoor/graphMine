from __future__ import annotations

from pathlib import Path

import pytest
from graphmine_agent.database import Database
from graphmine_agent.graph_store import GraphStore, UploadError
from graphmine_agent.models import (
    ConversationEvent,
    ExecutionPlan,
    FileRole,
    JobRecord,
    JobStatus,
    SessionRecord,
)


def test_canonical_graph_is_validated_and_described(
    graph_store: GraphStore, session: SessionRecord, triangle_graph: bytes
) -> None:
    record = graph_store.ingest(
        session_id=session.id,
        role=FileRole.graph,
        filename="triangle.json",
        content=triangle_graph,
        media_type="application/json",
    )
    assert record.metadata.vertex_count == 3
    assert record.metadata.edge_count == 3
    assert record.metadata.maximum_degree == 2
    assert record.sha256
    assert graph_store.execution_path(record.id, session.id).name == "graph.json"
    preview = graph_store.graph_preview(record.id, vertex_limit=2, edge_limit=1)
    assert preview["vertex_count"] == 3
    assert preview["vertices_truncated"] is True
    assert len(preview["vertices"]) == 2
    assert len(preview["edges"]) <= 1


def test_edge_list_is_normalized(
    graph_store: GraphStore, session: SessionRecord
) -> None:
    record = graph_store.ingest(
        session_id=session.id,
        role=FileRole.graph,
        filename="network.csv",
        content=b"source,target,weight,timestamp\na,b,1.5,10\nb,c,2,11\n",
        directed=True,
    )
    assert record.canonical_path
    assert record.metadata.directed
    assert record.metadata.has_weights
    assert record.metadata.has_timestamps


def test_file_cannot_cross_session_boundary(
    graph_store: GraphStore,
    database: Database,
    session: SessionRecord,
    triangle_graph: bytes,
) -> None:
    record = graph_store.ingest(
        session_id=session.id,
        role=FileRole.graph,
        filename="triangle.json",
        content=triangle_graph,
    )
    other = database.create_session(SessionRecord())
    with pytest.raises(UploadError, match="does not belong"):
        graph_store.execution_path(record.id, other.id)


def test_invalid_graph_does_not_enter_database(
    graph_store: GraphStore, database: Database, session: SessionRecord
) -> None:
    with pytest.raises(UploadError, match="endpoint"):
        graph_store.ingest(
            session_id=session.id,
            role=FileRole.graph,
            filename="invalid.json",
            content=b'{"graph":{"id":"x","directed":false,"allows_self_loops":false,"allows_parallel_edges":false},"vertices":[{"id":1}],"edges":[{"id":0,"source":1,"target":2}]}',
        )
    assert database.list_files(session.id) == []


def test_upload_filename_cannot_escape_session_workspace(
    graph_store: GraphStore, session: SessionRecord, triangle_graph: bytes
) -> None:
    record = graph_store.ingest(
        session_id=session.id,
        role=FileRole.graph,
        filename="../../outside.json",
        content=triangle_graph,
    )
    source = Path(record.source_path).resolve()
    allowed = (graph_store.settings.data_root / "sessions" / session.id).resolve()
    assert source.name == "outside.json"
    assert allowed in source.parents
    assert not (graph_store.settings.data_root / "outside.json").exists()


def test_upload_limit_is_enforced_before_persistence(
    graph_store: GraphStore, database: Database, session: SessionRecord
) -> None:
    with pytest.raises(UploadError, match="upload exceeds"):
        graph_store.ingest(
            session_id=session.id,
            role=FileRole.attachment,
            filename="large.bin",
            content=b"x" * (graph_store.settings.max_upload_bytes + 1),
        )
    assert database.list_files(session.id) == []


def test_restart_fails_only_interrupted_jobs_and_preserves_queued(
    database: Database, session: SessionRecord
) -> None:
    plan = ExecutionPlan(
        session_id=session.id,
        graph_id="file-placeholder",
        problem_id="maximal_clique_enumeration",
        operation_id="maximal-cliques",
    )
    running = database.save_job(
        JobRecord(session_id=session.id, plan=plan, status=JobStatus.running)
    )
    interpreting = database.save_job(
        JobRecord(session_id=session.id, plan=plan, status=JobStatus.interpreting)
    )
    queued = database.save_job(JobRecord(session_id=session.id, plan=plan))

    assert database.mark_interrupted_jobs_failed() == 2
    for job_id in (running.id, interpreting.id):
        recovered = database.get_job(job_id)
        assert recovered.status == JobStatus.failed
        assert recovered.error == {
            "code": "server_restarted",
            "message": "the agent server restarted while this job was active",
        }
    assert database.get_job(queued.id).status == JobStatus.queued


def test_event_replay_is_ordered_and_respects_cursor(
    database: Database, session: SessionRecord
) -> None:
    first = database.add_event(
        ConversationEvent(session_id=session.id, type="job.queued")
    )
    second = database.add_event(
        ConversationEvent(session_id=session.id, type="job.running")
    )
    assert [item.type for item in database.events(session.id)] == [
        "job.queued",
        "job.running",
    ]
    assert [item.type for item in database.events(session.id, first.sequence or 0)] == [
        "job.running"
    ]
    assert second.sequence and first.sequence and second.sequence > first.sequence
