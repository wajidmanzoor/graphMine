"""Compile result-only SET annotations without ever sending writes to Neo4j.

The read prefix and final row selection execute once in Neo4j. Prompt inputs
travel with those exact rows; we never rematch a projected graph to recover them.
"""

from dataclasses import dataclass, field

from .database_sources import json_value, validate_cypher
from .errors import AnalyticsError
from .semantic_loader import encoded, key
from .semantic_validation import arguments, prompt_fields, string_value, tokens, validate_semantic


def fail(message):
    raise AnalyticsError(message, "query_annotation", 422)


def identifier(token):
    if token.kind not in {"word", "identifier"}:
        fail("Use named nodes or relationships as annotation targets.")
    return token.text[1:-1].replace("``", "`") if token.kind == "identifier" else token.text


def split(items):
    parts, start, depth = [], 0, 0
    for i, token in enumerate(items):
        if token.kind != "symbol":
            continue
        if token.text in {"(", "[", "{"}:
            depth += 1
        elif token.text in {")", "]", "}"}:
            depth -= 1
        elif token.text == "," and depth == 0:
            parts.append(items[start:i]); start = i + 1
    parts.append(items[start:])
    return parts


@dataclass
class Assignment:
    variable: str
    property: str
    model: str
    expression: str
    inputs: list[str]
    column: str = ""
    rows: dict = field(default_factory=dict)


@dataclass
class AnnotationPlan:
    statement: str
    assignments: list[Assignment]
    used: int = 0

    def reset(self):
        self.used = 0
        for assignment in self.assignments:
            assignment.rows.clear()

    def visible(self, record):
        return {name: record[name] for name in record.keys() if not name.startswith("__gm_input_")}

    def capture(self, record, projected):
        for number, assignment in enumerate(self.assignments):
            target = projected.get(assignment.column)
            if not isinstance(target, dict) or len(target) != 1 or not ({"node", "relationship"} & target.keys()):
                fail(f"{assignment.variable} must return a real node or relationship for SET {assignment.variable}.{assignment.property}.")
            kind = "vertices" if "node" in target else "edges"
            identity = key(next(iter(target.values())))
            values = []
            for i in range(len(assignment.inputs)):
                value = json_value(record[f"__gm_input_{number}_{i}"])
                # Text bindings preserve heterogeneous JSON input values and
                # avoid the native parameter binder guessing a common type.
                values.append(value if isinstance(value, str) else encoded(value))
            previous = assignment.rows.get((kind, identity))
            if previous is not None and previous != values:
                fail(f"Multiple rows give {assignment.variable}.{assignment.property} different inputs. Group them with WITH and collect() before SET.")
            if previous is None:
                self.used += len(encoded(values).encode())
                if self.used > 64 * 1024 * 1024:
                    raise AnalyticsError("Model input rows exceed the 64 MiB budget. Narrow the source query.", "resource_limit")
            assignment.rows[(kind, identity)] = values


def compile_annotations(statement, aliases):
    items = tokens(statement)
    if items and items[-1].text == ";":
        items = items[:-1]
    depth, clauses = 0, []
    for i, token in enumerate(items):
        if token.kind == "symbol":
            if token.text in {"(", "[", "{"}:
                depth += 1
            elif token.text in {")", "]", "}"}:
                depth -= 1
        if depth == 0 and token.kind == "word" and token.text.upper() in {"SET", "RETURN", "ORDER", "SKIP", "LIMIT"} and (not i or items[i - 1].text not in {".", "$", ":", "AS"}):
            clauses.append((i, token.text.upper()))
    setters = [i for i, name in clauses if name == "SET"]
    model_calls = [t for i, t in enumerate(items[:-1]) if t.kind == "word" and t.text.upper().startswith("LLM") and items[i + 1].text == "("]
    if not setters and not model_calls:
        validate_cypher(statement)
        return None
    if len(setters) != 1:
        fail("Attach model output with SET node.summary = llm('qwen', '…') before RETURN. Use one SET clause with comma-separated attributes.")
    start = setters[0]
    returns = [i for i, name in clauses if name == "RETURN" and i > start]
    if len(returns) != 1:
        fail("Finish annotations with RETURN and the named nodes or relationships to display.")
    end = returns[0]
    suffix = next((i for i, name in clauses if i > end and name in {"ORDER", "SKIP", "LIMIT"}), len(items))
    returned = {}
    for part in split(items[end + 1:suffix]):
        if not part or len(part) not in {1, 3} or len(part) == 3 and part[1].text.upper() != "AS":
            fail("After SET, return named graph elements, optionally AS an alias. Put grouping or DISTINCT in WITH before SET.")
        name, column = identifier(part[0]), identifier(part[-1])
        if name in returned or column in returned.values():
            fail("Return each graph variable once with a unique column name.")
        returned[name] = column
    assignments, extra, assigned = [], [], set()
    for number, part in enumerate(split(items[start + 1:end])):
        if len(part) < 8 or part[1].text != "." or part[3].text != "=":
            fail("Use SET node.attribute = llm('qwen', '…') or SET edge.attribute = llm_score('qwen', '…').")
        variable, prop = identifier(part[0]), identifier(part[2])
        if variable not in returned:
            fail(f"Return {variable} explicitly so its generated {prop} attribute belongs to the result graph.")
        if prop.startswith(("__gm_", "gm_")) or prop == "neo4j_labels":
            fail("Choose an attribute name outside the reserved graph metadata fields.")
        if (variable, prop) in assigned:
            fail("Assign each graph attribute only once per query.")
        assigned.add((variable, prop))
        expression = part[4:]
        if expression[0].text.upper() not in {"LLM", "LLM_SCORE"} or expression[1].text != "(":
            fail("Each SET value must be llm() or llm_score(). Aggregate source inputs with WITH before SET.")
        args, closing = arguments(expression, 1)
        if closing != len(expression) - 1 or len(args) != 2 or any(len(arg) != 1 for arg in args):
            fail("Use two literal arguments: a configured model alias and a prompt.")
        model, prompt = (string_value(arg[0]) for arg in args)
        if model in {"mock", "mock:echo"}:
            fail("Use a real configured model alias, such as 'qwen'. Query annotations always call the model.")
        if model not in aliases:
            fail(f"Model alias '{model}' is not configured. Open Model configuration to see available aliases.")
        inputs, _ = prompt_fields(prompt)
        for i, value in enumerate(inputs):
            # prompt_fields has already validated expressions as read-only.
            prompt = prompt.replace("{{" + value + "}}", "{{gm_input_" + str(i) + "}}")
            extra.append(f"({value}) AS __gm_input_{number}_{i}")
        native = f"{expression[0].text}({encoded(model)}, {encoded(prompt)})"
        validate_semantic("RETURN " + native, aliases=aliases)
        assignments.append(Assignment(variable, prop, model, native, inputs, returned[variable]))
    if not assignments or len(assignments) > 8:
        fail("Use between one and eight generated attributes per query.")
    prefix = statement[:items[start].start]
    projection = statement[items[end].start:items[suffix - 1].end]
    tail = statement[items[suffix].start:items[-1].end] if suffix < len(items) else ""
    read = prefix + "\n" + projection + (", " + ", ".join(extra) if extra else "") + "\n" + tail
    read_items = tokens(read)
    for i, token in enumerate(read_items[:-2]):
        if token.kind in {"word", "identifier"} and read_items[i + 1].text == "." and read_items[i + 2].kind in {"word", "identifier"}:
            if (identifier(token), identifier(read_items[i + 2])) in assigned:
                fail("Generated attributes are available in the result graph. Filter and order source rows before SET; do not read a generated attribute in the same query.")
        if token.text.upper().startswith("LLM") and read_items[i + 1].text == "(":
            fail("Place model calls in SET annotations; source selection runs before the model.")
    if any(t.kind in {"word", "identifier"} and identifier(t).startswith("__gm_") for t in items):
        fail("Names beginning with __gm_ are reserved for query execution.")
    validate_cypher(read)
    return AnnotationPlan(read, assignments)


def prepare(runtime, body):
    from .semantic_policy import execution_policy
    from .semantic_providers import catalog
    aliases = {item["alias"] for item in catalog(runtime)["aliases"]}
    plan = compile_annotations(body.statement, aliases)
    if plan:
        from .semantic_engine import live_supported
        if not live_supported():
            raise AnalyticsError("Install the pinned semantic engine before running model annotations.", "semantic_unavailable", 503)
        if body.projection != "elements":
            fail("Use Existing graph mode for SET annotations on nodes and relationships.")
        for assignment in plan.assignments:
            execution_policy(runtime, request(body, assignment))
    return plan


def request(body, assignment):
    bindings = [f"gm_row.i{i} AS gm_input_{i}" for i in range(len(assignment.inputs))]
    return {"statement": "UNWIND $gm_rows AS gm_row WITH gm_row.ri AS gm_ri" + (", " + ", ".join(bindings) if bindings else "") +
            f" RETURN gm_ri, {assignment.expression} AS gm_value", "parameters": {}, "model": assignment.model,
            "call_limit": body.call_limit, "batch_size": body.batch_size, "timeout_seconds": body.model_timeout_seconds,
            "reuse_answers": False, "projection": "elements", "directed": body.directed}


def annotate(runtime, body, plan, graph):
    from .semantic_queries import evaluate
    from .semantic_policy import execution_policy
    from .database_job_context import checkpoint
    records = {kind: {key(v["id"]): v for v in graph[kind]} for kind in ("vertices", "edges")}
    targets_seen = set()
    for assignment in plan.assignments:
        for kind, identity in assignment.rows:
            target = (kind, identity, assignment.property)
            if target in targets_seen:
                fail("Different variables assign the same graph attribute. Return one target per assignment.")
            targets_seen.add(target)
    usage, steps, settings, engine = {}, [], [], None
    remaining = execution_policy(runtime, request(body, plan.assignments[0]))["call_limit"]
    effective_limit = remaining
    for assignment in plan.assignments:
        if not assignment.rows:
            continue
        if remaining < 1:
            raise AnalyticsError("The query reached its total model request limit. No result was published.", "semantic_call_limit", 422, details={"usage": usage})
        checkpoint("asking_model")
        targets = list(assignment.rows)
        query = request(body, assignment)
        query["call_limit"] = remaining
        query["parameters"] = {"gm_rows": [{"ri": i, **{f"i{n}": value for n, value in enumerate(values)}} for i, values in enumerate(assignment.rows.values())]}
        # The worker evaluates exact captured rows; graph identities are joined
        # only in the parent, against real records from the read transaction.
        empty = {"graph": graph["graph"], "vertices": [], "edges": []}
        try:
            result = evaluate(runtime, empty, query)
        except AnalyticsError as error:
            details = error.details if isinstance(error.details, dict) else {}
            combined = dict(usage)
            for name, value in details.get("usage", {}).items():
                if type(value) in {int, float}:
                    combined[name] = combined.get(name, 0) + value
            error.details = {**details, "usage": combined}
            raise
        answers = result["value"].get("rows", []) if result["kind"] == "table" else []
        seen = set()
        for answer in answers:
            i = answer.get("gm_ri")
            if type(i) is not int or not 0 <= i < len(targets) or i in seen or "gm_value" not in answer:
                fail("The model result did not match the selected graph rows. No result was published.")
            seen.add(i)
            kind, identity = targets[i]
            records[kind][identity].setdefault("attributes", {})[assignment.property] = answer["gm_value"]
        if len(seen) != len(targets):
            fail("The model returned incomplete graph annotations. No result was published.")
        for name, value in result["usage"].items():
            if type(value) in {int, float}:
                usage[name] = usage.get(name, 0) + value
        remaining -= result["usage"].get("http_requests", 0)
        steps.extend({**step, "target": f"{assignment.variable}.{assignment.property}"} for step in result["steps"])
        settings.append(result["effective_settings"]); engine = result["engine"]
    return {"usage": usage, "steps": steps, "engine": engine, "model_settings": settings,
            "model_dependent_input": bool(steps), "simulation": False,
            "requested_call_limit": body.call_limit, "effective_call_limit": effective_limit,
            "annotation_scope": "SET annotates selected result graph elements only; source selection and LIMIT run before model calls."}
