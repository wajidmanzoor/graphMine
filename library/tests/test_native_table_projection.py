"""SQL/Fraction oracles for native joins, graph projection, and aggregation."""

from copy import deepcopy
from fractions import Fraction
import random
import sqlite3

import pytest
import test_native_extended

native = test_native_extended.native
NativeError = test_native_extended.BINDING.NativeError


def fixture():
    rng = random.Random(98113)
    events = [
        {
            "from": str(rng.randrange(8)),
            "to": str(rng.randrange(8)),
            "amount": str(rng.randrange(1, 15)),
            "time": str(rng.randrange(5)),
        }
        for _ in range(160)
    ]
    accounts = [{"id": str(i), "region": "east" if i % 2 else "west"} for i in range(8)]

    def table(rows):
        return {"data": {"columns": list(rows[0]), "rows": rows}}

    tables = {"events": table(events), "accounts": table(accounts)}
    projection = {
        "version": 1,
        "id": "projection-test",
        "task": "shortest_paths",
        "edge_table": "events",
        "joins": [
            {
                "table": "accounts",
                "alias": "sender",
                "left": "events.from",
                "right": "id",
                "kind": "required",
                "cardinality": "many_to_one",
            }
        ],
        "source": {
            "field": "events.from",
            "type": "string",
            "attributes": {"region": {"field": "sender.region", "type": "string"}},
        },
        "target": {"field": "events.to", "type": "string"},
        "directed": True,
        "weight": {"field": "events.amount", "type": "integer", "meaning": "cost"},
        "timestamp": {"field": "events.time", "type": "integer"},
        "time_window": {"start": 1, "end": 4},
        "duplicates": "preserve",
    }
    return tables, projection


@pytest.mark.parametrize("policy", ["preserve", "sum", "min", "max", "count"])
@pytest.mark.parametrize("directed", [True, False])
def test_projection_matches_independent_sql_join_and_aggregation(
    native, policy, directed
):
    tables, projection = fixture()
    projection.update(duplicates=policy, directed=directed)
    if policy == "count":
        projection.pop("weight")
        projection["task"] = "ranking"
    result = native.project_graph(tables, projection)
    with sqlite3.connect(":memory:") as db:
        db.execute(
            "CREATE TABLE events (src TEXT, dst TEXT, amount INTEGER, time INTEGER)"
        )
        db.execute("CREATE TABLE accounts (id TEXT, region TEXT)")
        db.executemany(
            "INSERT INTO events VALUES (?,?,?,?)",
            [tuple(row.values()) for row in tables["events"]["data"]["rows"]],
        )
        db.executemany(
            "INSERT INTO accounts VALUES (?,?)",
            [tuple(row.values()) for row in tables["accounts"]["data"]["rows"]],
        )
        source, target = (
            ("src", "dst") if directed else ("min(src,dst)", "max(src,dst)")
        )
        aggregate = {
            "preserve": "amount",
            "sum": "sum(amount)",
            "min": "min(amount)",
            "max": "max(amount)",
            "count": "count(*)",
        }[policy]
        sql = f"SELECT {source}, {target}, time, {aggregate} FROM events JOIN accounts ON src=id WHERE time>=1 AND time<4"
        if policy != "preserve":
            sql += f" GROUP BY {source}, {target}, time"
        expected = sorted(db.execute(sql))
    observed = []
    for edge in result["graph"]["edges"]:
        u, v = edge["source"], edge["target"]
        if not directed:
            u, v = sorted((u, v))
        observed.append((u, v, edge["timestamp"], edge["weight"]))
    assert sorted(observed) == expected
    assert result["provenance"]["retained_rows"] == sum(
        1 <= int(row["time"]) < 4 for row in tables["events"]["data"]["rows"]
    )
    assert result["complete"]
    # The projected records are valid native graph inputs, not just table-shaped output.
    reached = native.run(
        "breadth-first-search",
        result["graph"],
        parameters={"sources": ["0"]},
        device="cpu",
    )
    assert reached["complete"] and len(reached["ports"]["vertices"]["value"]) == 8


@pytest.mark.parametrize("kind", ["left", "inner", "required"])
def test_missing_join_keys_are_explicit_and_counted(native, kind):
    tables, projection = fixture()
    tables["accounts"]["data"]["rows"] = tables["accounts"]["data"]["rows"][:3]
    projection["joins"][0]["kind"] = kind
    projection.pop("time_window")
    missing = sum(int(row["from"]) >= 3 for row in tables["events"]["data"]["rows"])
    if kind == "required":
        with pytest.raises(NativeError, match="unmatched"):
            native.project_graph(tables, projection)
    else:
        result = native.project_graph(tables, projection)
        assert result["provenance"]["joins"][0]["unmatched"] == missing
        assert len(result["graph"]["edges"]) == (
            160 - missing if kind == "inner" else 160
        )
        if kind == "left":
            assert any(
                row["attributes"].get("region") is None
                for row in result["graph"]["vertices"]
            )


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("cardinality", "cardinality"),
        ("unknown_column", "Unknown projection field"),
        ("meaning", "require cost"),
        ("duplicate", "Duplicate edge"),
        ("empty_unknown", "Unknown projection field"),
        ("type", "Integer conversion"),
        ("window", "start < end"),
        ("probability", "between zero and one"),
        ("cell", "Table cells must be text"),
        ("rows", "row limit"),
    ],
)
def test_projection_rejects_ambiguous_or_invalid_semantics(native, mutation, message):
    tables, projection = fixture()
    kwargs = {}
    if mutation == "cardinality":
        tables["accounts"]["data"]["rows"].append(
            deepcopy(tables["accounts"]["data"]["rows"][0])
        )
    elif mutation in ("unknown_column", "empty_unknown"):
        projection["target"]["field"] = "events.invented"
        if mutation == "empty_unknown":
            tables["events"]["data"]["rows"] = []
    elif mutation == "meaning":
        projection["weight"]["meaning"] = "strength"
    elif mutation == "duplicate":
        projection["duplicates"] = "reject"
    elif mutation == "type":
        tables["events"]["data"]["rows"][0]["time"] = "1.5"
    elif mutation == "window":
        projection["time_window"]["end"] = 0
    elif mutation == "probability":
        projection["task"] = "ranking"
        projection["weight"]["meaning"] = "probability"
    elif mutation == "cell":
        tables["events"]["data"]["rows"][0]["amount"] = 3
    else:
        kwargs["max_rows"] = 10
    with pytest.raises(NativeError, match=message):
        native.project_graph(tables, projection, **kwargs)


def test_typed_ids_exact_sums_empty_graph_and_conflicting_attributes(native):
    tables, projection = fixture()
    projection.update(joins=[], task="shortest_paths", duplicates="sum")
    projection.pop("timestamp")
    projection.pop("time_window")
    projection["source"] = {"field": "events.from", "type": "string"}
    projection["target"]["type"] = "integer"
    row = {"from": "001", "to": "1", "amount": "2", "time": "0"}
    tables["events"]["data"]["rows"] = [row, dict(row)]
    result = native.project_graph(tables, projection)
    assert [v["id"] for v in result["graph"]["vertices"]] == ["001", 1]
    assert result["graph"]["edges"][0]["weight"] == 4
    projection["weight"]["type"] = "number"
    tables["events"]["data"]["rows"][0]["amount"] = "0.1"
    tables["events"]["data"]["rows"][1]["amount"] = "0.2"
    assert Fraction(0.1) + Fraction(0.2) != Fraction(0.1 + 0.2)
    with pytest.raises(NativeError, match="not exactly representable"):
        native.project_graph(tables, projection)
    tables["events"]["data"]["rows"] = []
    empty = native.project_graph(tables, projection)
    assert empty["graph"]["vertices"] == empty["graph"]["edges"] == []
