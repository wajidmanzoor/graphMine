"""Computed analyst context and validation for evidence-linked prose and charts.

References and numeric consistency are machine checked. These checks do not
prove the semantic truth of arbitrary model-written prose; that remains an
explicit evaluation dimension. Chart data always comes from computed answers.
"""

from __future__ import annotations

import copy
import json
import math
import re
import shutil
import subprocess
from collections import Counter
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft7Validator
from jsonschema.exceptions import best_match

from .models import GroundedNarrative, GroundedStatement, VisualizationSpec

VERSION = "grounded-analysis-v2"
MAX_CHART_ROWS = 10000
MAX_VIEWS = 24
SCHEMA_URL = "https://vega.github.io/schema/vega-lite/v6.json"
NUMBER = re.compile(r"(?<![\w.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?")
DATUM_FIELD = re.compile(r"datum(?:\.([A-Za-z_]\w*)|\[['\"]([^'\"]+)['\"]\])")
CHART_REPAIR_GUIDANCE = (
    "Return the full corrected narrative. Preserve evidence references and use only supplied datasets. "
    "Each spec_json must be a valid JSON object serialized as a string, with balanced braces and brackets. "
    "hconcat, vconcat, concat and layer must be arrays of child specifications, not objects with a views key; "
    "put spacing beside hconcat/vconcat/concat. A filter transform has exactly one key, filter, "
    "whose value is a predicate; it has no join key. Check all chart specifications before returning."
)


def _scalar(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, int) and abs(value) > 2**53 - 1:
        return str(value)
    return (
        value if value is None or isinstance(value, (str, bool, int, float)) else None
    )


def _flat(row):
    result = {
        str(k): _scalar(v) for k, v in row.items() if not isinstance(v, (list, dict))
    }
    for key, value in row.get("attributes", {}).items():
        # Escaped field names are supplied in the context; no lossy name rewriting.
        result[f"attribute_{key}"] = _scalar(value)
    return result


def _columns(rows):
    names = sorted({key for row in rows for key in row})
    return {
        key: (
            "quantitative"
            if key not in {"id", "group_id", "entity_key", "key"}
            and (values := [row[key] for row in rows if row.get(key) is not None])
            and all(type(v) in {int, float} for v in values)
            else "nominal"
        )
        for key in names
    }


def prepare_analysis(answer: dict) -> dict:
    """Attach bounded chart tables and computed comparisons without model input."""
    datasets = {}
    extra_facts = []

    def add(name, rows, scope, description):
        if not rows:
            return
        shown = rows[:MAX_CHART_ROWS]
        datasets[name] = {
            "rows": shown,
            "columns": _columns(shown),
            "scope": scope,
            "description": description,
            "total_rows": len(rows),
            "shown_rows": len(shown),
            "truncated": len(rows) > len(shown),
        }

    def fact(identifier, statement, value, source):
        extra_facts.append(
            {
                "id": identifier,
                "statement": statement,
                "value": value,
                "source": source,
                "kind": "comparison",
            }
        )

    steps = answer.get("steps") or {"answer": answer}
    for step_id, step in steps.items():
        prefix = "" if step_id == "answer" else step_id + "_"
        scope = "answer" if step_id == "answer" else f"answer.steps.{step_id}"
        members = [_flat(row) for row in step.get("rows", [])]
        for row in members:
            row["entity_key"] = row.pop("key", str(row.get("id", "")))
        add(
            prefix + "members",
            members,
            scope,
            "Returned entities and original attributes; not all input entities unless the computation returned them all.",
        )
        groups = [
            {
                "group": group["label"],
                "group_id": str(group["id"]),
                "size": group["size"],
            }
            for group in step.get("groups", [])
        ]
        add(
            prefix + "groups",
            groups,
            scope,
            "Returned groups; sizes include overlapping members in each group.",
        )
        member_lookup = {row["entity_key"]: row for row in members}
        memberships = [
            {
                **member_lookup.get(key, {"entity_key": key}),
                "group": group["label"],
                "group_id": str(group["id"]),
            }
            for group in step.get("groups", [])
            for key in group.get("member_keys", [])
        ]
        add(
            prefix + "memberships",
            memberships,
            scope,
            "One row per returned group membership. Counting rows counts memberships, not unique entities.",
        )
        add(
            prefix + "relationships",
            [_flat(row) for row in step.get("edge_rows", [])],
            scope,
            "Computed relationship values.",
        )
        add(
            prefix + "patterns",
            [_flat(row) for row in step.get("pattern_rows", [])],
            scope,
            "Verified supplied-pattern counts and materialization status.",
        )
        add(
            prefix + "events",
            [_flat(row) for row in step.get("events", [])],
            scope,
            "Matched events; use the recorded timestamp unit, not an inferred calendar date.",
        )
        add(
            prefix + "metrics",
            [
                {"metric": str(k), "value": v}
                for k, v in step.get("metrics", {}).items()
                if type(v) in {int, float} and math.isfinite(v)
            ],
            scope,
            "Computed result metrics with distinct meanings; units are not interchangeable.",
        )

        for column, kind in _columns(members).items():
            if kind != "quantitative" or column in {"id", "entity_key", "rank"}:
                continue
            values = [
                row[column] for row in members if type(row.get(column)) in {int, float}
            ]
            if not values:
                continue
            low, high = min(values), max(values)
            name = prefix + "range_" + re.sub(r"\W", "_", column)
            fact(
                name,
                f"Among the {len(values)} returned entities with {column}, the minimum is {low:g} and the maximum is {high:g}; the difference is {high - low:g}.",
                {
                    "count": len(values),
                    "minimum": low,
                    "maximum": high,
                    "difference": high - low,
                },
                f"{scope}.rows",
            )
        attributes = sorted(
            {key for row in members for key in row if key.startswith("attribute_")}
        )[:12]
        profiles = []
        for column in attributes:
            counts = Counter(
                json.dumps(row.get(column), ensure_ascii=False, sort_keys=True)
                for row in members
            )
            for value, count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )[:100]:
                label = json.loads(value)
                profiles.append(
                    {
                        "attribute": column,
                        "category": "Missing" if label is None else str(label),
                        "count": count,
                        "denominator": len(members),
                        "percent": 100 * count / len(members),
                    }
                )
            if counts:
                leading, count = min(
                    counts.items(), key=lambda item: (-item[1], item[0])
                )
                label = json.loads(leading)
                fact(
                    prefix + "profile_" + re.sub(r"\W", "_", column),
                    f"For {column} among returned entities, {label if label is not None else 'missing values'} accounts for {count} of {len(members)} ({100 * count / len(members):.2f}%). Tied categories may share the largest count.",
                    {
                        "category": label,
                        "count": count,
                        "denominator": len(members),
                        "percent": 100 * count / len(members),
                    },
                    f"{scope}.rows",
                )
        add(
            prefix + "attribute_counts",
            profiles,
            scope,
            "Attribute counts among returned entities. Missing values are retained in denominators; each attribute has its own distribution. At most 100 categories per attribute are shown.",
        )
        original_groups = step.get("groups", [])
        if 1 < len(original_groups) <= 30 and all(
            "member_keys" in g for g in original_groups
        ):
            overlap = []
            for left in original_groups:
                a = set(left["member_keys"])
                for right in original_groups:
                    b = set(right["member_keys"])
                    overlap.append(
                        {
                            "group_a": left["label"],
                            "group_b": right["label"],
                            "shared": len(a & b),
                            "union": len(a | b),
                            "jaccard": len(a & b) / len(a | b) if a | b else 0,
                        }
                    )
            add(
                prefix + "overlap",
                overlap,
                scope,
                "Returned membership overlap, including the diagonal. Zero overlap does not establish disconnected groups.",
            )

    answer["analysis_datasets"] = datasets
    existing = {item["id"] for item in answer["facts"]}
    answer["facts"].extend(item for item in extra_facts if item["id"] not in existing)
    return answer


def analysis_context(answer: dict) -> dict:
    return {
        "version": VERSION,
        "datasets": {
            name: {
                **{k: v for k, v in table.items() if k != "rows"},
                "sample_rows": table["rows"][:6],
            }
            for name, table in answer.get("analysis_datasets", {}).items()
        },
        "chart_data_rule": "Use data: {name: <exact dataset name>}. The server binds all recorded rows. Sample rows are only examples, never the complete dataset unless shown_rows equals their count.",
        "chart_schema": SCHEMA_URL,
        "numeric_rule": "Concrete numerical claims must be supported by the cited fact statements/values. Request a new computation when the supplied evidence cannot answer the question.",
    }


def validate_statement(statement: GroundedStatement, facts: dict):
    if not set(statement.fact_ids) <= facts.keys():
        raise ValueError("Explanation refers to unknown evidence")
    evidence = " ".join(
        json.dumps(facts[key], ensure_ascii=False) for key in statement.fact_ids
    )
    allowed = [float(token.replace(",", "")) for token in NUMBER.findall(evidence)]
    for token in NUMBER.findall(statement.text):
        value = float(token.replace(",", ""))
        if not any(
            math.isclose(value, expected, rel_tol=0.0001, abs_tol=0.005)
            for expected in allowed
        ):
            raise ValueError(f"Explanation contains an unsupported number: {token}")


@lru_cache(maxsize=1)
def _schema_validator():
    schema = json.loads(
        (Path(__file__).parent / "static/vendor/vega-lite-schema.json").read_text()
    )
    return Draft7Validator(schema)


def _field_name(value):
    return value.replace("\\.", ".").replace("\\[", "[").replace("\\]", "]")


def _validate_composition_shape(node, path="$", depth=0):
    """Expose actionable errors otherwise buried in Vega-Lite's schema unions."""
    if depth > 40:
        raise ValueError("Visualization nesting is too deep")
    if not isinstance(node, dict):
        return  # The complete schema validator reports other type errors.
    for key in ("layer", "hconcat", "vconcat", "concat"):
        if key not in node:
            continue
        children = node[key]
        if not isinstance(children, list):
            raise ValueError(  # noqa: TRY004 -- serialized input validation
                f"Invalid Vega-Lite at {path}.{key}: expected an array of child "
                "specifications, not a views wrapper. Put spacing beside the composition key."
            )
        for index, child in enumerate(children):
            _validate_composition_shape(child, f"{path}.{key}[{index}]", depth + 1)
    if "spec" in node:
        _validate_composition_shape(node["spec"], f"{path}.spec", depth + 1)
    if isinstance(node.get("transform"), list):
        for index, transform in enumerate(node["transform"]):
            if isinstance(transform, dict) and "filter" in transform:
                extra = sorted(set(transform) - {"filter"})
                if extra:
                    raise ValueError(
                        f"Invalid Vega-Lite at {path}.transform[{index}]: a filter "
                        f"transform accepts only the filter key; remove {extra}."
                    )


def _schema_error_message(error):
    path = "$" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}"
        for part in error.absolute_path
    )
    # Do not fill the repair context with the whole invalid chart instance.
    if error.validator == "type":
        detail = f"expected type {error.validator_value}"
    elif error.validator in {"anyOf", "oneOf"}:
        detail = "does not match a supported Vega-Lite specification; check composition, mark, encoding and transforms"
    elif error.validator == "enum":
        detail = f"expected one of {error.validator_value}"
    else:
        detail = error.message
    return f"Invalid Vega-Lite schema at {path}: {detail[:400]}"


def validate_vega_spec(spec: dict, datasets: dict) -> set[str]:
    """Validate the grammar and every data source/field before client execution."""
    if not isinstance(spec, dict):
        raise ValueError("A Vega-Lite specification must be an object")  # noqa: TRY004 -- serialized input validation
    if spec.get("$schema", SCHEMA_URL) != SCHEMA_URL:
        raise ValueError("Use the installed Vega-Lite v6 schema")
    if len(json.dumps(spec, allow_nan=False)) > 60000:
        raise ValueError("Visualization specification exceeds 60 KB")
    _validate_composition_shape(spec)
    if error := best_match(_schema_validator().iter_errors(spec)):
        raise ValueError(_schema_error_message(error))
    referenced = set()
    nodes = 0

    def inspect(value, depth=0):
        nonlocal nodes
        if depth > 40:
            raise ValueError("Visualization nesting is too deep")
        if isinstance(value, dict):
            if any(
                key in value
                for key in (
                    "url",
                    "href",
                    "datasets",
                    "usermeta",
                    "__proto__",
                    "constructor",
                    "prototype",
                )
            ):
                raise ValueError(
                    "Visualization may only use application-bound data and supported properties"
                )
            if (
                value.get("mark") == "image"
                or isinstance(value.get("mark"), dict)
                and value["mark"].get("type") == "image"
            ):
                raise ValueError("Image marks are not supported")
            if "mark" in value:
                nodes += 1
            if "data" in value:
                data = value["data"]
                if (
                    not isinstance(data, dict)
                    or set(data) != {"name"}
                    or data["name"] not in datasets
                ):
                    raise ValueError(
                        "Each chart data source must name a supplied dataset"
                    )
                referenced.add(data["name"])
            for child in value.values():
                inspect(child, depth + 1)
        elif isinstance(value, list):
            if len(value) > 500:
                raise ValueError("Visualization array exceeds the supported bound")
            for child in value:
                inspect(child, depth + 1)
        elif isinstance(value, str) and len(value) > 2400:
            raise ValueError("Visualization expression or label is too long")

    inspect(spec)
    if not referenced or not 1 <= nodes <= MAX_VIEWS:
        raise ValueError(
            "A visualization must contain 1–24 views backed by supplied data"
        )

    def fields(value, columns):
        if isinstance(value, dict):
            for key, child in value.items():
                if (
                    key == "field"
                    and isinstance(child, str)
                    and _field_name(child) not in columns
                ):
                    raise ValueError(f"Unknown visualization field: {child}")
                fields(child, columns)
        elif isinstance(value, list):
            for child in value:
                fields(child, columns)

    def view(node, inherited):
        columns = (
            set(datasets[node["data"]["name"]]["columns"])
            if "data" in node
            else set(inherited)
        )
        for transform in node.get("transform", []):
            # Lookups have their own source fields; validate them independently.
            if "lookup" in transform:
                if _field_name(transform["lookup"]) not in columns:
                    raise ValueError("Unknown lookup field")
                source = transform["from"]
                source_columns = datasets[source["data"]["name"]]["columns"]
                if (
                    source["key"] not in source_columns
                    or not set(source.get("fields", [])) <= source_columns.keys()
                ):
                    raise ValueError("Unknown lookup source field")
                aliases = transform.get("as", source.get("fields", []))
                columns.update([aliases] if isinstance(aliases, str) else aliases)
                continue
            fields(transform, columns)
            for field in transform.get("groupby", []):
                if _field_name(field) not in columns:
                    raise ValueError(f"Unknown grouping field: {field}")
            for expression_key in ("calculate", "filter"):
                expression = transform.get(expression_key)
                if isinstance(expression, str):
                    for first, second in DATUM_FIELD.findall(expression):
                        if (first or second) not in columns:
                            raise ValueError(
                                "Expression references an unknown data field"
                            )
            if "aggregate" in transform:
                columns = set(transform.get("groupby", [])) | {
                    item["as"] for item in transform["aggregate"]
                }
            for family in ("joinaggregate", "window"):
                columns.update(item["as"] for item in transform.get(family, []))
            aliases = transform.get("as", [])
            columns.update([aliases] if isinstance(aliases, str) else aliases)
            if "fold" in transform:
                if not set(transform["fold"]) <= columns:
                    raise ValueError("Fold references unknown fields")
                columns.update(transform.get("as", ["key", "value"]))
            if "pivot" in transform:
                raise ValueError(
                    "Use a layered, faceted or rect-mark view instead of data-dependent pivot field names"
                )
        for key in ("encoding", "facet", "repeat"):
            if key in node:
                fields(node[key], columns)
        for key in ("layer", "hconcat", "vconcat", "concat"):
            for child in node.get(key, []):
                view(child, columns)
        if "spec" in node:
            view(node["spec"], columns)

    view(spec, set())
    return referenced


def compile_vega(spec: dict) -> dict:
    executable = shutil.which("node")
    script = Path(__file__).parents[1] / "visualization/validate.mjs"
    if executable is None:
        raise ValueError("The local visualization compiler is unavailable")
    try:
        result = subprocess.run(
            [executable, str(script)],
            input=json.dumps(spec, allow_nan=False),
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        report = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise ValueError(
            "The visualization compiler did not complete successfully"
        ) from error
    if result.returncode or not report.get("ok") or report.get("warnings"):
        raise ValueError(
            f"Visualization compilation/rendering failed: {report.get('error') or report.get('warnings')}"
        )
    return report


def validate_narrative(
    narrative: GroundedNarrative,
    answer: dict,
    defaults: list,
    supported_operations: set[str],
    *,
    compile_charts: bool = True,
) -> list[VisualizationSpec]:
    facts = {fact["id"]: fact for fact in answer["facts"]}
    if not set(narrative.fact_ids) <= facts.keys():
        raise ValueError("Narrative selected unknown facts")
    if not set(narrative.view_ids) <= {view.id for view in defaults}:
        raise ValueError("Narrative selected unknown default views")
    for statement in (
        [narrative.summary] if narrative.summary else []
    ) + narrative.findings:
        validate_statement(statement, facts)
    if narrative.analysis_request:
        if (
            not narrative.analysis_operation_ids
            or not set(narrative.analysis_operation_ids) <= supported_operations
        ):
            raise ValueError("Further analysis must identify supported operations")
    elif narrative.analysis_operation_ids:
        raise ValueError("Further-analysis operations require an explicit question")
    views = []
    for index, chart in enumerate(narrative.charts):
        if not set(chart.fact_ids) <= facts.keys():
            raise ValueError("Chart references unknown facts")
        try:
            spec = json.loads(chart.spec_json)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"charts[{index}].spec_json must contain valid JSON: {error.msg} "
                f"at line {error.lineno}, column {error.colno}. Check commas and balanced braces/brackets."
            ) from error
        used = validate_vega_spec(spec, answer.get("analysis_datasets", {}))
        spec = copy.deepcopy(spec)
        # Inline only verified rows, after validating that the proposal had no data.
        spec["datasets"] = {
            name: answer["analysis_datasets"][name]["rows"] for name in sorted(used)
        }
        if compile_charts:
            compile_vega(spec)
        notices = [
            f"{name}: displaying {answer['analysis_datasets'][name]['shown_rows']} of {answer['analysis_datasets'][name]['total_rows']} rows."
            for name in sorted(used)
            if answer["analysis_datasets"][name]["truncated"]
        ]
        scopes = {answer["analysis_datasets"][name]["scope"] for name in used}
        views.append(
            VisualizationSpec(
                id=f"custom_{index}",
                type="vega_lite",
                title=chart.title,
                data_ref="answer.analysis_datasets",
                description=" ".join([chart.description, *notices]),
                encodings={"answer_ref": next(iter(scopes))}
                if len(scopes) == 1
                else {},
                vega_lite=spec,
                evidence_ids=chart.fact_ids,
                interactions=["filter", "brush", "select_row"],
            )
        )
    return views


def apply_narrative(interpretation, narrative, answer):
    if narrative.summary:
        interpretation.summary = narrative.summary.text
    explanation = (
        [narrative.summary] if narrative.summary else []
    ) + narrative.findings
    interpretation.explanation = explanation
    # Original computed facts remain visible separately from model explanation.
    if narrative.analysis_request:
        from .models import FollowupAction

        interpretation.requires_new_execution = True
        interpretation.proposed_request = narrative.analysis_request
        interpretation.followup_actions.append(
            FollowupAction(
                id="analyst_additional_analysis",
                label=narrative.analysis_request,
                kind="ask",
                request=narrative.analysis_request,
            )
        )
        interpretation.suggested_followups.append(narrative.analysis_request)
    return interpretation


def analyst_payload(answer, defaults, catalog, domain_id, user_message):
    """Shared complete evidence input for live analysis and teacher examples."""
    from .presentation import followup_options

    payload = {
        "task": "Explain the computed evidence in relation to the user's question and design useful custom visualizations. Cite supplied facts, preserve limitations, and request another supported computation if evidence is insufficient.",
        "user_message": user_message,
        "analysis_context": analysis_context(answer),
        "domain": catalog.domain(domain_id).model_dump(mode="json"),
        "answer": {
            "question": answer["question"],
            "facts": answer["facts"][:60],
            "limitations": answer["limitations"],
            "provenance": answer["provenance"],
        },
        "supported_operations": [
            {
                "operation_id": key,
                "description": catalog.problem(catalog.operation(key).problem_id)[
                    "spec"
                ]["problem_statement"],
            }
            for key in catalog.instructions
        ],
        "default_visualizations": [item.model_dump(mode="json") for item in defaults],
        "followup_options": followup_options(answer),
    }
    return payload
