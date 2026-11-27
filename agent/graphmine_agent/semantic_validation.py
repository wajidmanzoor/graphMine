"""A deliberately bounded, read-only Tentō dialect, including prompt expressions."""

from dataclasses import dataclass
import re

from .errors import AnalyticsError


FORBIDDEN = set("CREATE MERGE SET DELETE DETACH REMOVE DROP ALTER RENAME COPY LOAD INSTALL UNINSTALL ATTACH DETACH IMPORT EXPORT CALL USE FOREACH INSERT UPDATE GRANT DENY REVOKE BEGIN COMMIT ROLLBACK CHECKPOINT COMMENT EXPLAIN PROFILE".split())
READ_START = {"MATCH", "OPTIONAL", "WITH", "UNWIND", "RETURN"}
KEYWORDS = READ_START | set("WHERE AND OR XOR NOT IN AS DISTINCT CASE WHEN THEN ELSE END ORDER BY SKIP LIMIT UNION ALL EXISTS COUNT COLLECT STATE INITIAL SHORTEST ACYCLIC TRAIL".split())
FUNCTIONS = set("COUNT COLLECT SUM AVG MIN MAX ABS CEIL FLOOR ROUND SQRT SIGN POW POWER LOG EXP RANGE SIZE LENGTH COALESCE NULLIF LOWER UPPER TRIM LTRIM RTRIM REPLACE SUBSTRING LEFT RIGHT SPLIT CONCAT STARTS_WITH ENDS_WITH CONTAINS CAST TO_STRING TO_INT64 TO_DOUBLE TO_BOOLEAN TYPE LABEL LABELS ID NODES RELS RELATIONSHIPS START_NODE END_NODE STARTNODE ENDNODE PREVIOUS PROPERTIES STRUCT_PACK STRUCT_EXTRACT UNION_VALUE UNION_TAG UNION_EXTRACT LIST_CONTAINS LIST_EXTRACT LIST_SLICE LIST_APPEND LIST_CONCAT LIST_DISTINCT LIST_SORT LIST_REVERSE LIST_TRANSFORM LIST_FILTER LIST_REDUCE ANY ALL NONE SINGLE ISFINITE HASH MD5 SHA256 HAS_LABEL LABELS_OF GRAPH_ID HAS_PROPERTY PROPERTY_NAMES SUBGRAPH".split())
MODEL_ARGUMENTS = {"LLM": (0, 1), "LLM_SCORE": (0, 1), "LLM_AGG": (1, 2),
                   "LLM_PATH_AGG": (1, 2), "LLM_SG_AGG": (2, 3)}
FUNCTIONS.update(MODEL_ARGUMENTS)


@dataclass(frozen=True)
class Token:
    text: str
    kind: str
    start: int
    end: int


def reject(message="Use one read-only semantic query. Writes, procedures and external loading are unavailable."):
    raise AnalyticsError(message, "semantic_read_only", 422)


def tokens(text):
    result, i = [], 0
    while i < len(text):
        start, ch = i, text[i]
        if ch.isspace():
            i += 1
            continue
        if text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                break
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                reject("Close the block comment before running this query.")
            i = end + 2
            continue
        if ch in "'\"`":
            i += 1
            while i < len(text):
                if text[i] == ch:
                    if i + 1 < len(text) and text[i + 1] == ch:
                        i += 2
                        continue
                    i += 1
                    break
                if text[i] == "\\" and ch != "`":
                    i += 2
                else:
                    i += 1
            else:
                reject("Close the quoted string or identifier before running this query.")
            if i > len(text):
                reject()
            result.append(Token(text[start:i], "identifier" if ch == "`" else "string", start, i))
        elif ch.isascii() and (ch.isalpha() or ch == "_"):
            i += 1
            while i < len(text) and text[i].isascii() and (text[i].isalnum() or text[i] == "_"):
                i += 1
            result.append(Token(text[start:i], "word", start, i))
        else:
            i += 1
            result.append(Token(ch, "symbol", start, i))
    return result


def string_value(token):
    if token.kind != "string":
        reject("Model aliases and prompts must be string literals.")
    text, quote, result, i = token.text[1:-1], token.text[0], [], 0
    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "\\": "\\", "'": "'", '"': '"'}
    while i < len(text):
        ch = text[i]
        if text.startswith(quote * 2, i):
            result.append(quote); i += 2
        elif ch == "\\":
            i += 1
            if i >= len(text):
                reject()
            if text[i] in {"u", "U"}:
                size = 4 if text[i] == "u" else 8
                value = text[i + 1:i + 1 + size]
                if len(value) != size or not re.fullmatch("[0-9a-fA-F]+", value):
                    reject("Invalid Unicode escape in prompt.")
                try:
                    result.append(chr(int(value, 16)))
                except ValueError:
                    reject("Invalid Unicode escape in prompt.")
                i += 1 + size
            else:
                if text[i] not in escapes:
                    reject("Unsupported string escape in semantic query.")
                result.append(escapes[text[i]]); i += 1
        else:
            result.append(ch); i += 1
    return "".join(result)


def arguments(items, opening):
    stack, parts, start = [], [], opening + 1
    for i in range(opening, len(items)):
        text = items[i].text
        if items[i].kind in {"string", "identifier"}:
            continue
        if text in {"(", "[", "{"}:
            stack.append(text)
        elif text in {")", "]", "}"}:
            if not stack or stack.pop() != {")": "(", "]": "[", "}": "{"}[text]:
                reject("Unbalanced delimiters in semantic query.")
            if not stack:
                parts.append(items[start:i])
                return parts, i
        elif text == "," and len(stack) == 1:
            parts.append(items[start:i]); start = i + 1
    reject("Unbalanced delimiters in semantic query.")


def prompt_fields(prompt):
    inputs, masked, offset = [], list(prompt), 0
    while True:
        begin = prompt.find("{{", offset)
        if begin < 0:
            break
        depth, end, i, quote = 0, None, begin + 2, None
        while i < len(prompt):
            ch = prompt[i]
            if quote:
                if ch == "\\" and quote != "`":
                    i += 2; continue
                if ch == quote:
                    if prompt[i:i + 2] == quote * 2:
                        i += 2; continue
                    quote = None
            elif ch in "'\"`":
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                if depth:
                    depth -= 1
                elif prompt[i:i + 2] == "}}":
                    end, expression = i + 2, prompt[begin + 2:i]
                    break
            i += 1
        if end is None:
            reject("Close each {{input expression}} in the prompt.")
        expression_tokens = tokens(expression)
        depth = 0
        for i, token in enumerate(expression_tokens):
            if token.kind == "symbol" and token.text in {"(", "[", "{"}:
                depth += 1
            elif token.kind == "symbol" and token.text in {")", "]", "}"}:
                depth -= 1
            elif depth == 0 and token.text == "," and i + 1 < len(expression_tokens) and expression_tokens[i + 1].text.upper() == "IMAGE":
                reject("Images are unavailable in semantic queries.")
        _validate(expression_tokens, allow_models=False, expression=True)
        inputs.append(expression)
        masked[begin:end] = " " * (end - begin)
        offset = end
    outputs = []
    for match in re.finditer(r"\{\s*([A-Za-z_]\w*)\s+((?:STRING|BOOLEAN|BOOL|INT64|INTEGER|INT|BIGINT|DOUBLE|FLOAT|REAL|NUMBER|LIST|STRUCT)\b[^{}]*)\}", "".join(masked), re.I):
        outputs.append({"name": match[1], "type": match[2].strip()})
    return inputs, outputs


def _validate(items, *, allow_models=True, expression=False):
    if not items or not expression and items[0].text.upper() not in READ_START:
        reject()
    if any(t.text == ";" and t.kind == "symbol" for t in items[:-1]) or expression and any(t.text == ";" for t in items):
        reject("Run one semantic statement at a time.")
    stack, steps = [], []
    for i, token in enumerate(items):
        value, previous = token.text.upper(), items[i - 1].text.upper() if i else ""
        following = items[i + 1].text if i + 1 < len(items) else ""
        if token.kind == "symbol":
            if token.text in {"(", "[", "{"}:
                stack.append(token.text)
            elif token.text in {")", "]", "}"}:
                if not stack or stack.pop() != {")": "(", "]": "[", "}": "{"}[token.text]:
                    reject("Unbalanced delimiters in semantic query.")
        if token.kind == "word" and value in FORBIDDEN:
            # Property/parameter names and map keys are data, not clauses.
            if previous not in {".", "$", ":", "AS"} and following not in {":", "."}:
                reject()
        if token.kind not in {"word", "identifier"} or following != "(":
            continue
        name = token.text.strip("`").replace("``", "`").upper()
        if token.kind == "word" and name in KEYWORDS:
            continue
        if name not in FUNCTIONS:
            reject("This function is unavailable in the semantic read dialect.")
        if name in MODEL_ARGUMENTS:
            if not allow_models:
                reject("Nested model calls inside prompt inputs are unavailable.")
            parts, _ = arguments(items, i + 1)
            model_index, prompt_index = MODEL_ARGUMENTS[name]
            if name == "LLM_SG_AGG" and len(parts) > 1 and len(parts[1]) == 1 and parts[1][0].kind == "string":
                model_index, prompt_index = 1, 2
            if len(parts) <= prompt_index or len(parts[model_index]) != 1 or len(parts[prompt_index]) != 1:
                reject("Use literal model aliases and prompts in semantic functions.")
            model = string_value(parts[model_index][0])
            if model not in {"mock", "mock:echo", "qwen"}:
                reject("Choose an approved model alias: mock or qwen.")
            prompt = string_value(parts[prompt_index][0])
            inputs, outputs = prompt_fields(prompt)
            if name == "LLM_SCORE":
                if outputs:
                    reject("A score prompt describes what to rate; its integer score output is automatic.")
                outputs = [{"name": "score", "type": "INT64"}]
            elif not outputs:
                outputs = [{"name": "result", "type": "STRING"}]
            steps.append({"kind": name.lower(), "model_alias": model, "prompt": prompt,
                          "inputs": inputs, "outputs": outputs})
    if stack:
        reject("Unbalanced delimiters in semantic query.")
    return steps


def validate_semantic(statement):
    return _validate(tokens(statement))
