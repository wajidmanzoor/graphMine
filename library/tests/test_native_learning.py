"""Objective, gradient, inference and held-out isolation checks for native models."""

from __future__ import annotations

import itertools
from copy import deepcopy
from fractions import Fraction

import numpy as np
import pytest
import test_native_extended
from scipy.special import logsumexp, softmax
from test_native_extended import BINDING, canonical, run

native = test_native_extended.native


def propagate(graph, features, layers, *, weighted=False):
    n = len(graph["vertices"])
    indices = {v["id"]: i for i, v in enumerate(graph["vertices"])}
    adjacency = np.eye(n)
    for edge in graph["edges"]:
        u, v = indices[edge["source"]], indices[edge["target"]]
        if u == v:
            continue
        if weighted:
            adjacency[u, v] += edge.get("weight", 1)
            adjacency[v, u] += edge.get("weight", 1)
        else:
            adjacency[v, u] = 1
            if not graph["graph"]["directed"]:
                adjacency[u, v] = 1
    matrix = adjacency / adjacency.sum(axis=1)[:, None]
    return np.linalg.matrix_power(matrix, layers) @ np.asarray(features)


def check_linear_inference(
    result, features, targets, training_indices, task, l2, id_field="vertex", ids=None
):
    state = result["model_state"]
    coefficients = np.asarray(state["coefficients"])
    design = np.column_stack(
        (
            (features - np.array(state["feature_mean"]))
            / np.array(state["feature_scale"]),
            np.ones(len(features)),
        )
    )
    logits = design @ coefficients
    values = softmax(logits, axis=1) if task == "classification" else logits
    index = {
        v: i for i, v in enumerate(ids if ids is not None else range(len(features)))
    }
    for row in result["predictions"]:
        i = index[row[id_field]]
        if task == "classification":
            np.testing.assert_allclose(row["probabilities"], values[i], atol=1e-12)
            assert row["prediction"] == state["classes"][int(np.argmax(values[i]))]
        else:
            assert row["prediction"] == pytest.approx(values[i, 0], abs=1e-12)
    x = design[training_indices]
    if task == "classification":
        y = np.array([state["classes"].index(targets[i]) for i in training_indices])
        residual = values[training_indices].copy()
        residual[np.arange(len(y)), y] -= 1
        loss = np.mean(
            logsumexp(logits[training_indices], axis=1) - logits[training_indices, y]
        )
    else:
        residual = (
            logits[training_indices]
            - np.array([targets[i] for i in training_indices])[:, None]
        )
        loss = np.mean(residual**2) / 2
    gradient = x.T @ residual / len(training_indices) + l2 * coefficients
    loss += l2 * np.sum(coefficients**2) / 2
    summary = result["training_summary"]
    assert summary["attained_loss"] == pytest.approx(loss, abs=1e-10)
    assert summary["gradient_norm"] == pytest.approx(
        np.linalg.norm(gradient), abs=1e-10
    )
    assert summary["attained_loss"] <= summary["initial_loss"] + 1e-12
    assert all(
        b <= a + 1e-12
        for a, b in zip(summary["loss_history"], summary["loss_history"][1:])
    )
    for split in ("train", "validation", "test"):
        rows = [
            r
            for r in result["predictions"]
            if r["split"] == split and targets.get(index[r[id_field]]) is not None
        ]
        metric = result["metrics"][split]
        assert metric["labeled_count"] == len(rows)
        if not rows:
            continue
        if task == "classification":
            assert metric["accuracy"] == sum(
                r["prediction"] == targets[index[r[id_field]]] for r in rows
            ) / len(rows)
        else:
            assert metric["mean_squared_error"] == pytest.approx(
                np.mean(
                    [(r["prediction"] - targets[index[r[id_field]]]) ** 2 for r in rows]
                )
            )
    return design, coefficients


@pytest.mark.parametrize("task", ["classification", "regression"])
def test_native_node_learning_objective_and_label_isolation(native, task):
    graph = canonical(7, [(0, 1), (1, 2), (3, 4), (4, 5)])
    features = np.array(
        [[-3, 0], [-2, 1], [-1, 0], [1, 0], [2, 1], [3, 0], [0, 4]], dtype=float
    )
    targets = {
        i: (
            int(i >= 3)
            if task == "classification"
            else 2 * features[i, 0] - features[i, 1]
        )
        for i in range(6)
    }
    train = [0, 2, 3, 5]
    args = {
        "task": task,
        "vertex_features": {
            "rows": [
                {"vertex": i, "value": row.tolist()} for i, row in enumerate(features)
            ]
        },
        "training_labels": {
            "rows": [{"vertex": i, "value": targets[i]} for i in train]
        },
        "split": {
            "train": train,
            "validation": [1],
            "test": [4],
            "validation_labels": [{"vertex": 1, "value": targets[1]}],
            "test_labels": [{"vertex": 4, "value": targets[4]}],
        },
        "model_definition": {
            "architecture": "sgc",
            "layers": 1,
            "epochs": 1000,
            "l2": 0.2,
            "tolerance": 1e-8,
            "random_seed": 54,
        },
    }
    result = run(native, "node-learning", graph, **args)["result"]
    representation = propagate(graph, features, 1)
    design, coefficients = check_linear_inference(
        result, representation, targets, train, task, 0.2
    )
    np.testing.assert_allclose(
        result["model_state"]["feature_mean"], representation[train].mean(axis=0)
    )
    if task == "regression":
        expected = np.linalg.solve(
            design[train].T @ design[train] / len(train) + 0.2 * np.eye(3),
            design[train].T @ np.array([targets[i] for i in train]) / len(train),
        )
        np.testing.assert_allclose(coefficients[:, 0], expected, atol=2e-7)
    changed = deepcopy(args)
    changed["split"]["validation_labels"][0]["value"] = 93
    changed["split"]["test_labels"][0]["value"] = -73
    again = run(native, "node-learning", graph, **changed)["result"]
    assert result["model_state"] == again["model_state"]
    assert result["predictions"] == again["predictions"]
    assert result["metrics"] != again["metrics"]
    changed["split"]["test"] = [0]
    with pytest.raises(BINDING.NativeError, match="disjoint"):
        run(native, "node-learning", graph, **changed)


def test_native_graph_learning_permutation_and_inference(native):
    graphs = [
        canonical(n, [(i, i + 1) for i in range(n - 1)]) for n in (1, 2, 3, 4, 5, 6, 0)
    ]
    for i, graph in enumerate(graphs):
        graph["graph"]["id"] = f"graph-{i}"
    ids = [g["graph"]["id"] for g in graphs]
    targets = {i: len(g["edges"]) for i, g in enumerate(graphs)}
    args = {
        "task": "regression",
        "graph_labels": {
            "rows": [{"graph": ids[i], "value": targets[i]} for i in range(4)]
        },
        "split": {
            "train": ids[:4],
            "validation": [ids[4]],
            "test": ids[5:],
            "validation_labels": [{"graph": ids[4], "value": targets[4]}],
            "test_labels": [{"graph": ids[i], "value": targets[i]} for i in (5, 6)],
        },
        "model_definition": {
            "architecture": "mean_graph_convolution",
            "readout": "sum",
            "layers": 2,
            "epochs": 600,
            "l2": 0.1,
            "random_seed": 6,
        },
    }
    data = {"dataset_id": "graphs", "graphs": graphs}
    result = run(native, "graph-learning", data, **args)["result"]
    representations = []
    for graph in graphs:
        n = len(graph["vertices"])
        if not n:
            representations.append([0, 0, 0])
            continue
        degree = [
            sum(v in (e["source"], e["target"]) for e in graph["edges"])
            for v in range(n)
        ]
        features = np.column_stack((np.ones(n), degree, degree))
        representations.append(propagate(graph, features, 2).sum(axis=0))
    check_linear_inference(
        result,
        np.array(representations),
        targets,
        list(range(4)),
        "regression",
        0.1,
        "graph",
        ids,
    )
    reordered = deepcopy(data)
    for graph in reordered["graphs"]:
        graph["vertices"].reverse()
        graph["edges"].reverse()
    again = run(native, "graph-learning", reordered, **args)["result"]
    np.testing.assert_allclose(
        result["model_state"]["coefficients"],
        again["model_state"]["coefficients"],
        atol=1e-12,
    )
    assert result["predictions"] == again["predictions"]


def test_native_hypergraph_learning_incidence_and_label_isolation(native):
    features = np.array([[-2, 1], [-1, 0], [2, 1], [1, 0], [0, 2], [5, 0]], dtype=float)
    targets = {0: 0, 1: 0, 2: 1, 3: 1, 4: 1}
    graph = {
        "graph": {"id": "incidence"},
        "vertices": [
            {
                "id": i,
                "attributes": {
                    "features": row.tolist(),
                    "split": "train"
                    if i in (0, 2, 4)
                    else "test"
                    if i in (1, 3)
                    else "inference",
                    **({"target": targets[i]} if i in targets else {}),
                },
            }
            for i, row in enumerate(features)
        ],
        "hyperedges": [
            {"id": 0, "vertices": [0, 1, 4], "weight": 2},
            {"id": 1, "vertices": [2, 3], "weight": 3},
            {"id": 2, "vertices": [4], "weight": 1},
        ],
    }
    args = {
        "model": "hgnn-linear-v1",
        "seed": 99,
        "model_parameters": {"layers": 2, "epochs": 500, "l2": 0.1},
    }
    result = run(native, "hypergraph-node-learning", graph, **args)["result"]
    incidence = np.zeros((6, 3))
    for j, edge in enumerate(graph["hyperedges"]):
        incidence[edge["vertices"], j] = 1
    weights = np.array([2, 3, 1])
    degree = incidence @ weights
    matrix = incidence @ np.diag(weights / incidence.sum(axis=0)) @ incidence.T
    for i in range(6):
        if degree[i]:
            matrix[i] /= degree[i]
        else:
            matrix[i, i] = 1
    check_linear_inference(
        result, matrix @ matrix @ features, targets, [0, 2, 4], "classification", 0.1
    )
    changed = deepcopy(graph)
    changed["vertices"][1]["attributes"]["target"] = "different held-out label"
    assert (
        run(native, "hypergraph-node-learning", changed, **args)["result"][
            "model_state"
        ]
        == result["model_state"]
    )


@pytest.mark.parametrize("model", ["line", "deepwalk", "node2vec"])
def test_native_node_embeddings_loss_and_gradient(native, model):
    graph = canonical(
        4, [(0, 1, 2), (0, 1, 1), (0, 2, 1), (1, 2, 2), (2, 0, 1)], directed=True
    )
    options = {"epochs": 250, "l2": 0.02, "learning_rate": 3}
    if model != "line":
        options.update(walk_length=5, walks_per_vertex=3, window=2)
    if model == "node2vec":
        options.update(p=0.5, q=2)
    args = {
        "model": model,
        "dimensions": 2,
        "training_parameters": options,
        "random_seed": 374,
    }
    result = run(native, "node-embedding", graph, **args)["result"]
    embedding = np.array([r["values"] for r in result["embeddings"]])
    context = np.array([r["values"] for r in result["context_embeddings"]])
    mass = np.zeros((4, 4))
    for row in result["training_summary"]["training_pairs"]:
        mass[row["source"], row["target"]] = float(
            Fraction(int(row["mass"]["numerator"]), int(row["mass"]["denominator"]))
        )
    if model == "line":
        np.testing.assert_array_equal(
            mass, [[0, 3, 1, 0], [0, 0, 2, 0], [1, 0, 0, 0], [0, 0, 0, 0]]
        )
    target = mass / mass.sum()
    scores = embedding @ context.T
    probabilities = softmax(scores, axis=1)
    residual = target.sum(axis=1)[:, None] * probabilities - target
    gradient_e, gradient_c = (
        residual @ context + 0.02 * embedding,
        residual.T @ embedding + 0.02 * context,
    )
    loss = np.sum(target * (logsumexp(scores, axis=1)[:, None] - scores)) + 0.01 * (
        np.sum(embedding**2) + np.sum(context**2)
    )
    summary = result["training_summary"]
    assert summary["attained_loss"] == pytest.approx(loss, abs=1e-10)
    assert summary["gradient_norm"] == pytest.approx(
        np.sqrt(np.sum(gradient_e**2) + np.sum(gradient_c**2)), abs=1e-10
    )
    assert summary["attained_loss"] < summary["initial_loss"]
    assert result == run(native, "node-embedding", graph, **args)["result"]


def test_native_knowledge_embedding_objective_ranking_and_isolation(native):
    graph = canonical(5, [(0, 1), (1, 2), (2, 3), (3, 0), (4, 4)], directed=True)
    for row in graph["edges"]:
        row["type"] = "r" if row["id"] < 3 else "s"
    validation = [
        {"source": 0, "type": "r", "target": 2},
        {"source": 1, "type": "s", "target": 3},
    ]
    options = {
        "epochs": 400,
        "learning_rate": 3,
        "l2": 0.0001,
        "negative_samples": 3,
        "random_seed": 123,
    }
    args = {
        "model": "distmult",
        "dimensions": 3,
        "training_triples": [0, 1, 3, 4],
        "validation_triples": validation,
        "training_parameters": options,
    }
    result = run(native, "knowledge-graph-embedding", graph, **args)["result"]
    entities = np.array([r["values"] for r in result["entity_embeddings"]])
    relations = {
        r["relation"]: np.array(r["values"]) for r in result["relation_embeddings"]
    }
    summary = result["training_summary"]
    gradient_e = 0.0001 * entities.copy()
    gradient_r = {name: 0.0001 * value.copy() for name, value in relations.items()}
    loss = 0.00005 * (
        np.sum(entities**2) + sum(np.sum(r * r) for r in relations.values())
    )

    def score(u, relation, v):
        return float(
            np.sum(
                (entities[u].astype(np.longdouble) * entities[v]) * relations[relation],
                dtype=np.longdouble,
            )
        )

    examples = summary["training_examples"]
    for row in examples:
        u, v, relation, positive = (
            row["source"],
            row["target"],
            row["type"],
            row["positive"],
        )
        value = score(u, relation, v)
        loss += np.logaddexp(0, -value if positive else value) / len(examples)
        residual = (1 / (1 + np.exp(-value)) - positive) / len(examples)
        gradient_e[u] += residual * relations[relation] * entities[v]
        gradient_e[v] += residual * relations[relation] * entities[u]
        gradient_r[relation] += residual * entities[u] * entities[v]
    assert summary["attained_loss"] == pytest.approx(loss, abs=1e-10)
    assert summary["gradient_norm"] == pytest.approx(
        np.sqrt(
            np.sum(gradient_e**2) + sum(np.sum(g * g) for g in gradient_r.values())
        ),
        abs=1e-10,
    )
    known = {
        (r["source"], r["type"], r["target"]) for r in examples if r["positive"]
    } | {(r["source"], r["type"], r["target"]) for r in validation}
    ranks = []
    for row in summary["validation_metrics"]["rankings"]:
        triple = row["source"], row["type"], row["target"]
        scores = []
        for entity in range(5):
            candidate = (
                (entity, triple[1], triple[2])
                if row["side"] == "head"
                else (triple[0], triple[1], entity)
            )
            if candidate not in known:
                scores.append(score(*candidate))
        value = score(*triple)
        rank = (
            1 + sum(s > value for s in scores) + 0.5 * sum(s == value for s in scores)
        )
        assert row["rank"] == rank
        ranks.append(rank)
    assert summary["validation_metrics"]["mean_reciprocal_rank"] == pytest.approx(
        np.mean(1 / np.array(ranks))
    )
    args["validation_triples"] = []
    without_validation = run(native, "knowledge-graph-embedding", graph, **args)[
        "result"
    ]
    assert without_validation["entity_embeddings"] == result["entity_embeddings"]
    assert without_validation["relation_embeddings"] == result["relation_embeddings"]
    assert without_validation["training_summary"]["training_examples"] == examples


def spherical_distance(a, b):
    # Independent atan2 of the cross/dot product of unit Cartesian positions.
    def unit(point):
        lat, lon = np.radians([point["latitude"], point["longitude"]])
        return np.array(
            [np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)]
        )

    x, y = unit(a), unit(b)
    return 6371.0088 * np.arctan2(np.linalg.norm(np.cross(x, y)), np.dot(x, y))


def test_native_geolocation_geodesic_energy_and_heldout_error(native):
    graph = canonical(6, [(0, 1, 1), (1, 2, 2), (2, 3, 1), (3, 4, 2)])
    seeds = [
        {"vertex": 0, "latitude": 10, "longitude": 179},
        {"vertex": 4, "latitude": 10, "longitude": -179},
    ]
    definition = {
        "objective": "seed_location_medoid_energy",
        "evaluation_locations": [{"vertex": 2, "latitude": 10, "longitude": 180}],
    }
    result = run(
        native,
        "graph-geolocation",
        graph,
        method_family="spatial_propagation",
        seed_locations={"rows": seeds},
        method_definition=definition,
    )["result"]
    locations = {r["vertex"]: r["location"] for r in result["locations"]}
    assert locations[5] is None
    for seed in seeds:
        assert locations[seed["vertex"]] == {
            k: seed[k] for k in ("latitude", "longitude")
        }
    energy = sum(
        e["weight"] * spherical_distance(locations[e["source"]], locations[e["target"]])
        for e in graph["edges"]
    )
    assert result["propagation_summary"][
        "attained_energy_weighted_km"
    ] == pytest.approx(energy, abs=1e-8)
    assert result["converged"]
    history = result["propagation_summary"]["energy_history"]
    assert all(b <= a + 1e-8 for a, b in itertools.pairwise(history))
    for v in (1, 2, 3):
        neighbors = [
            (e["target"] if e["source"] == v else e["source"], e["weight"])
            for e in graph["edges"]
            if v in (e["source"], e["target"])
        ]
        attained = sum(
            w * spherical_distance(locations[v], locations[u]) for u, w in neighbors
        )
        assert attained == pytest.approx(
            min(
                sum(w * spherical_distance(seed, locations[u]) for u, w in neighbors)
                for seed in seeds
            ),
            abs=1e-8,
        )
    error = spherical_distance(locations[2], definition["evaluation_locations"][0])
    assert 100 < error < 120
    assert result["evaluation_metrics"]["mean_geodesic_error_km"] == pytest.approx(
        error, abs=1e-8
    )


def test_native_condensation_gradient_objective_and_utility(native):
    graph = canonical(6, [(0, 1, 2), (1, 4, 1), (2, 3, 2), (3, 5, 1)])
    features = [[-2, 0], [-1, 1], [2, 0], [1, 1], [-1.5, 0.5], [1.5, 0.5]]
    targets = [0, 0, 1, 1, 0, 1]
    for v in range(6):
        graph["vertices"][v]["attributes"] = {
            "features": features[v],
            "label": targets[v],
            "split": "train" if v < 4 else "validation" if v == 4 else "test",
        }
    options = {
        "epochs": 200,
        "l2": 0,
        "tolerance": 1e-8,
        "layers": 1,
        "downstream_epochs": 200,
        "downstream_l2": 0.1,
        "evaluation_seeds": [1, 2],
    }
    args = {
        "synthetic_vertex_budget": 2,
        "method": "gradient_matching_linear_sgc_v1",
        "seed": 41,
        "method_parameters": options,
    }
    result = run(native, "graph-condensation", graph, **args)["result"]
    synthetic = result["synthetic_graph"]
    assert len(synthetic["vertices"]) == 2 and not synthetic["edges"]
    assert not {v["id"] for v in graph["vertices"]} & {
        v["id"] for v in synthetic["vertices"]
    }
    representation = propagate(graph, features, 1, weighted=True)
    design = np.column_stack((representation[:4], np.ones(4)))
    residual = np.full((4, 2), 0.5)
    residual[np.arange(4), targets[:4]] -= 1
    target_gradient = design.T @ residual / 4
    z = np.array([v["attributes"]["features"] for v in synthetic["vertices"]])
    synthetic_targets = [v["attributes"]["label"] for v in synthetic["vertices"]]
    synthetic_residual = np.full((2, 2), 0.5)
    synthetic_residual[np.arange(2), synthetic_targets] -= 1
    actual_gradient = np.column_stack((z, np.ones(2))).T @ synthetic_residual / 2
    metadata = result["training_metadata"]
    np.testing.assert_allclose(metadata["target_gradient"], target_gradient, atol=1e-12)
    np.testing.assert_allclose(
        metadata["synthetic_gradient"], actual_gradient, atol=1e-12
    )
    assert metadata["attained_loss"] == pytest.approx(
        np.sum((actual_gradient - target_gradient) ** 2) / 2, abs=1e-12
    )
    assert metadata["attained_loss"] < metadata["initial_loss"]
    for row in result["utility_metrics"]["runs"]:
        for kind in ("baseline", "condensed"):
            output = row[kind]
            for split, vertex in (("validation", 4), ("test", 5)):
                prediction = next(
                    p for p in output["predictions"] if p["vertex"] == vertex
                )
                assert output["metrics"][split]["accuracy"] == (
                    prediction["prediction"] == targets[vertex]
                )
        combined_features = np.vstack((z, representation))
        combined_targets = {
            0: synthetic_targets[0],
            1: synthetic_targets[1],
            6: targets[4],
            7: targets[5],
        }
        combined_ids = [v["id"] for v in synthetic["vertices"]] + list(range(6))
        check_linear_inference(
            row["condensed"],
            combined_features,
            combined_targets,
            [0, 1],
            "classification",
            0.1,
            ids=combined_ids,
        )
    changed = deepcopy(graph)
    changed["vertices"][4]["attributes"]["label"] = 92
    changed["vertices"][5]["attributes"]["label"] = 93
    again = run(native, "graph-condensation", changed, **args)["result"]
    assert [
        v["attributes"]["features"] for v in again["synthetic_graph"]["vertices"]
    ] == z.tolist()
    assert again["training_metadata"]["attained_loss"] == metadata["attained_loss"]
    with pytest.raises(BINDING.NativeError, match="training class"):
        run(
            native,
            "graph-condensation",
            graph,
            **{**args, "synthetic_vertex_budget": 1},
        )


def test_native_all_formal_contracts_have_profiles(native):
    catalog = native.catalog()
    formal = [p for p in catalog["problems"] if p["id"] != "graph_record_queries"]
    assert len(formal) == 70
    assert all(problem["operations"] for problem in formal)
    assert {p["id"] for p in formal} <= {
        op["problem_id"] for op in catalog["operations"]
    }
