#!/usr/bin/env python3
"""Generate native planner/validator schemas; no Python algorithm is embedded."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = {"type": ["integer", "string"], "minLength": 1}
NUMBER = {"type": "number"}
POSITIVE = {"type": "number", "exclusiveMinimum": 0}
NONNEGATIVE = {"type": "number", "minimum": 0}
BOOL = {"type": "boolean"}
TEXT = {"type": "string", "minLength": 1}
SEED = {"type": "integer", "minimum": 0}


def array(items, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum}


def obj(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def choice(*values):
    return {"enum": list(values)}


def integer(minimum=1):
    return {"type": "integer", "minimum": minimum}


OPTIMIZER = {
    "optimizer": choice("gradient_descent"),
    "epochs": integer(),
    "learning_rate": POSITIVE,
    "l2": NONNEGATIVE,
    "tolerance": POSITIVE,
}
READOUT = {
    **OPTIMIZER,
    "standardize": BOOL,
    "prediction_split": choice("all", "train", "validation", "test", "inference"),
}
FILTERS = array(
    obj(
        {
            "field": TEXT,
            "op": choice(
                "eq",
                "ne",
                "lt",
                "lte",
                "gt",
                "gte",
                "in",
                "not_in",
                "contains",
                "exists",
            ),
            "value": {},
        },
        ("field", "op", "value"),
    )
)
SCHEMAS = {}
for operation in (
    "node-lookup",
    "edge-filter",
    "neighbors",
    "common-neighbors",
    "query-paths",
    "graph-aggregate",
    "query-subgraph",
):
    SCHEMAS[operation] = {
        name: FILTERS
        for name in (
            "filters",
            "vertex_filters",
            "edge_filters",
            "source_filters",
            "target_filters",
        )
    }
    SCHEMAS[operation].update(vertices=array(ID), edge_ids=array(ID))

for operation, entity in (("node-learning", "vertex"), ("graph-learning", "graph")):
    label = array(
        obj(
            {entity: ID, "value": {"type": ["integer", "string", "number"]}},
            (entity, "value"),
        )
    )
    split = obj(
        {
            "train": array(ID, 1),
            "validation": array(ID),
            "test": array(ID),
            "policy": choice("transductive"),
            "validation_labels": label,
            "test_labels": label,
        },
        ("train",),
    )
    model = {
        **READOUT,
        "architecture": choice(
            "sgc" if entity == "vertex" else "mean_graph_convolution"
        ),
        "layers": integer(),
        "direction": choice("incoming", "outgoing", "undirected_projection"),
        "self_loops": choice("replace_with_single_self_message"),
        "parallel_edges": choice("collapse"),
        "random_seed": SEED,
    }
    if entity == "graph":
        model.update(
            feature_source=choice("structural", "attributes"),
            feature_key=TEXT,
            readout=choice("sum", "mean"),
        )
    SCHEMAS[operation] = {
        "task": choice("classification", "regression"),
        "split": split,
        "training_labels" if entity == "vertex" else "graph_labels": obj(
            {"rows": label}, ("rows",)
        ),
        "model_definition": obj(model, ("architecture",)),
    }
    if entity == "vertex":
        SCHEMAS[operation]["vertex_features"] = obj(
            {
                "rows": array(
                    obj({"vertex": ID, "value": array(NUMBER, 1)}, ("vertex", "value")),
                    1,
                )
            },
            ("rows",),
        )

SCHEMAS["hypergraph-node-learning"] = {
    "model": choice("hgnn-linear-v1"),
    "model_parameters": obj({**READOUT, "layers": integer()}),
}
SCHEMAS["node-embedding"] = {
    "model": choice("line", "deepwalk", "node2vec"),
    "dimensions": integer(),
    "training_parameters": obj(
        {
            **OPTIMIZER,
            "loss": choice("full_softmax"),
            "walk_length": integer(),
            "walks_per_vertex": integer(),
            "window": integer(),
            "p": POSITIVE,
            "q": POSITIVE,
            "self_loops": choice("reject", "drop", "keep"),
            "parallel_edges": choice("sum"),
            "direction": choice("preserve", "undirected_projection"),
        }
    ),
}
SCHEMAS["knowledge-graph-embedding"] = {
    "model": choice("distmult"),
    "dimensions": integer(),
    "training_triples": array(ID, 1),
    "validation_triples": array(
        obj({"source": ID, "type": TEXT, "target": ID}, ("source", "type", "target"))
    ),
    "training_parameters": obj(
        {
            **OPTIMIZER,
            "loss": choice("logistic_negative_sampling"),
            "negative_samples": integer(),
            "random_seed": SEED,
        }
    ),
}
LOCATION = obj(
    {
        "vertex": ID,
        "latitude": {"type": "number", "minimum": -90, "maximum": 90},
        "longitude": {"type": "number", "minimum": -180, "maximum": 180},
    },
    ("vertex", "latitude", "longitude"),
)
SCHEMAS["graph-geolocation"] = {
    "method_family": choice("spatial_propagation"),
    "seed_locations": obj({"rows": array(LOCATION)}, ("rows",)),
    "method_definition": obj(
        {
            "objective": choice("seed_location_medoid_energy"),
            "metric": choice("haversine_km"),
            "max_iterations": integer(),
            "tolerance_km": NONNEGATIVE,
            "self_loops": choice("reject"),
            "parallel_edges": choice("sum"),
            "evaluation_locations": array(LOCATION),
        },
        ("objective",),
    ),
}
SCHEMAS["graph-condensation"] = {
    "method": choice("gradient_matching_linear_sgc_v1"),
    "synthetic_vertex_budget": integer(),
    "method_parameters": obj(
        {
            **OPTIMIZER,
            "layers": integer(),
            "parallel_edges": choice("sum"),
            "downstream_epochs": integer(),
            "downstream_learning_rate": POSITIVE,
            "downstream_l2": NONNEGATIVE,
            "evaluation_seeds": array(SEED, 1),
        }
    ),
}

if __name__ == "__main__":
    path = ROOT / "library/manifests/native_parameter_schemas.json"
    path.write_text(json.dumps(SCHEMAS, indent=2, sort_keys=True) + "\n")
