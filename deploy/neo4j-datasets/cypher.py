"""Statement boundaries for the publisher's unchanged Cypher blocks."""

import re


TOKEN = re.compile(
    r"'(?:\\.|''|[^'\\])*'|\"(?:\\.|\"\"|[^\"\\])*\"|`(?:``|[^`])*`|"
    r"//[^\n]*|/\*[\s\S]*?\*/|;|[^'\"`/;]+|.", re.S
)


def statements(text):
    """Split only outside strings, backtick identifiers and comments.

    Each source header starts a separate published block. The publisher does
    not consistently put semicolons between distinct HTML code blocks.
    """
    for block in re.split(r"(?m)(?=^// Source: https://pgraphbenchweb\.vercel\.app/)", text):
        start = 0
        meaningful = False
        for token in TOKEN.finditer(block):
            value = token.group()
            if value == ";":
                if meaningful:
                    yield block[start:token.start()].strip()
                start, meaningful = token.end(), False
            elif not value.startswith(("//", "/*")) and value.strip():
                meaningful = True
        if meaningful:
            yield block[start:].strip()


def check_batches(value):
    """APOC can return a successful transaction containing failed inner batches."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"failedBatches", "failedOperations"} and int(item or 0) > 0:
                raise ValueError(f"APOC reported {key}={item}")
            if key in {"errorMessages", "failedParams", "wasTerminated"} and item:
                raise ValueError(f"APOC reported {key}: {item}")
            check_batches(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            check_batches(item)
