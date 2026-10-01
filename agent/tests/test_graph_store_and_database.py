from __future__ import annotations

import pytest
from graphmine_agent.database import Database
from graphmine_agent.graph_store import GraphStore, UploadError
from graphmine_agent.models import FileRole, SessionRecord


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
