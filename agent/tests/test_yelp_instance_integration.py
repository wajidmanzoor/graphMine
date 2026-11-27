"""Execute the required unchanged publisher examples against local Yelp when available."""

from pathlib import Path

import pytest

pytest.importorskip("neo4j")
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from graphmine_agent.database_queries import CypherRequest, execute_query
from graphmine_agent.database_sources import DatabaseSource, neo4j_session


@pytest.fixture
def yelp_instance(settings):
    repository = Path(__file__).resolve().parents[2]
    credentials = repository / ".database-workspace/demo.env"
    if not credentials.is_file():
        pytest.skip("The local Yelp instance is not configured")
    source = DatabaseSource(id="benchmark-yelp", name="Yelp", users=["*"],
                            neo4j_uri="bolt://127.0.0.1:17701", neo4j_password_env="GRAPHMINE_NEO4J_YELP_PASSWORD")
    if not any(line.strip().removeprefix("export ").partition("=")[0] == source.neo4j_password_env
               for line in credentials.read_text().splitlines()):
        pytest.skip("The local demo has no isolated Yelp instance configured")
    source._registry_password_file = credentials
    source._catalog = {"id": "yelp", "registry": True}
    source._backend_settings = settings
    try:
        with neo4j_session(source) as session:
            session.run("RETURN 1").consume()
    except (ServiceUnavailable, SessionExpired):
        pytest.skip("The local Yelp instance is offline")
    return repository, source


@pytest.mark.parametrize("query", ["Q01", "Q02", "Q08", "Q24"])
def test_published_yelp_query_through_app_read_path(yelp_instance, query):
    repository, source = yelp_instance
    statement = (repository / "deploy/neo4j-datasets/yelp/queries" / (query + ".cypher")).read_text()
    graph, lineage, sample, rows, table = execute_query(source, CypherRequest(statement=statement), 64 * 1024 * 1024)
    assert rows > 0
    assert lineage == {"vertices": {}, "edges": {}}
    assert all("GM_" not in label for vertex in graph["vertices"] for label in vertex["attributes"].get("neo4j_labels", []))
