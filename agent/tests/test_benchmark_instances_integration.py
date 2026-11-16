"""Concurrent authenticated requests against two real, verified local instances."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path

import pytest

from graphmine_agent.neo4j_registry import ready_datasets
from test_connectors import sources  # noqa: F401


@pytest.mark.skipif(os.getenv("GRAPHMINE_TEST_BENCHMARK_INTEGRATION") != "1",
                    reason="requires the verified local Yelp and MovieLens instances")
def test_two_users_query_real_instances_and_keep_snapshots_private(sources):
    client, runtime, alice, bob, *_ = sources
    repository = Path(__file__).resolve().parents[2]
    runtime.settings = replace(
        runtime.settings,
        neo4j_datasets_registry=repository / "deploy/neo4j-datasets/registry.json",
        neo4j_instances_root=Path(os.getenv("GRAPHMINE_LAB_DATA_ROOT", "/data/labdata/wajid/graphmine_data")) / "neo4j-instances",
        neo4j_datasets_password_file=repository / ".database-workspace/demo.env",
    )
    if not {"yelp", "movielens-32m"}.issubset({row["id"] for row in ready_datasets(runtime.settings)}):
        pytest.skip("Both isolated datasets must pass verification first")

    def query(slug, headers):
        return client.post(f"/api/database-sources/benchmark-{slug}/queries", headers=headers,
                           json={"dataset_id": slug, "statement": "MATCH (start:User) RETURN start LIMIT 1"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(query, "yelp", alice)
        b = pool.submit(query, "movielens-32m", bob)
        first, second = a.result(), b.result()
    assert first.status_code == second.status_code == 201, (first.text, second.text)
    for response, slug, key in ((first, "yelp", "user_id"), (second, "movielens-32m", "userId")):
        result = response.json()
        vertex = result["graph"]["vertices"][0]
        assert vertex["id"].startswith("neo4j:" + slug + ":")
        assert key in vertex["attributes"]
        provenance = result["dataset"]["source"]
        assert provenance["database_dataset"]["id"] == slug
        assert provenance["database_dataset"]["script_hashes"]
        assert provenance["lineage"] == {"vertices": {}, "edges": {}}
    other_snapshot = second.json()["dataset"]["id"]
    assert client.post(f"/api/database-query-snapshots/{other_snapshot}/chat", headers=alice, json={}).status_code == 404
    assert client.post(f"/api/database-query-snapshots/{other_snapshot}/chat", headers=bob, json={}).status_code == 201
