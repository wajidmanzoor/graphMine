"""Reader-facing pages generated from the same contracts as the runtime."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/wajidmanzoor/graphMine/blob/main/"


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def devices(op, device):
    names = [f"`{b['id']}`" for b in op["backends"] if b["device"] == device and b["compiled"]]
    return ", ".join(names) or "—"


def quality(op):
    return op["quality"].replace("_", " ").capitalize()


def generated_pages(document):
    reading = json.loads((ROOT / "catalog/problem_reading_guide.json").read_text())
    assert set(reading) == {p["id"] for p in document["problems"]}, "Reading guide must cover every problem"
    operations = {op["id"]: op for op in document["operations"]}
    pages = {}
    for family in document["families"]:
        members = [p for p in document["problems"] if p["family"] == family["id"]]
        lines = [f"# {family['title']}", "", "Find the right problem in this family, understand its contract, and choose a compiled operation to run.", "",
                 family["description"], "", f"**Start with this question:** {family['deciding_question']}", "",
                 "[Explore these operations](../explorer.md#family/" + family["id"] + ") · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)", "",
                 "The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.", "",
                 "Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.", "",
                 "## Problems in this family", ""]
        for p in members:
            lines.append(f"- [{p['name']}](#{p['id']})")
        for p in members:
            spec = p["spec"]
            guide = reading[p["id"]]
            lines += ["", f"## {p['name']} {{#{p['id']}}}", "", spec["problem_statement"], "",
                      "$$", guide["formula"], "$$", "", guide["notation"], "",
                      f"**Example question:** “{guide['question']}”", ""]
            req = spec.get("graph_input", {}).get("requirements", {})
            if req:
                lines += ["**Input assumptions.** " + "; ".join(f"{k.replace('_', ' ')}: {str(v).replace('_', ' ')}" for k,v in req.items()) + ".", ""]
            semantics = spec.get("solution_semantics", {})
            if semantics.get("exactness"):
                lines += ["**Guarantee.** " + semantics["exactness"], ""]
            if spec.get("required_outputs"):
                lines += ["**Required outputs:** " + ", ".join(f"`{x['name']}`" for x in spec["required_outputs"]) + ".", ""]
            lines += ["### Available operations", "", "| Operation | CPU | GPU | Quality |", "| --- | --- | --- | --- |"]
            for oid in p["operation_ids"]:
                op=operations[oid]
                lines.append(f"| [`{oid}`](../explorer.md#problem/{p['id']}) | {devices(op, 'cpu')} | {devices(op, 'gpu')} | {quality(op)} |")
            for oid in p["operation_ids"]:
                op=operations[oid]
                lines += ["", f"**`{oid}`** — {op['description']}"]
            lines += ["", "### Run it", "", "After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.", "",
                      "```sh", f"graphmine-native run {p['operation_ids'][0]} INPUT.json \\", "  --parameters PARAMETERS.json --device cpu", "```", "",
                      f"The [operation details](../explorer.md#problem/{p['id']}) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.", ""]
            if p.get("contract"):
                lines += [f"[Full formal contract]({REPO}{p['contract']}) · [Native API and implementation](../../library/code-reference.md)", ""]
            lines += ["### Research references", "", "These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.", ""]
            for a in p["research_algorithms"]:
                title=cell(a["title"])
                link=f"[{title}]({a['publication_url']})" if a.get("publication_url") else title
                code=f" · [Author code]({a['code_url']})" if a.get("code_url") else ""
                lines.append(f"- {link}. {a.get('venue') or 'Research reference'}, {a.get('year') or 'date not recorded'}{code}.{(' ' + a['note']) if a.get('note') else ''}")
            if not p["research_algorithms"]:
                lines.append("This utility group has no separate research-paper entry in the catalog.")
        pages[f"problem/families/{family['id']}.md"] = "\n".join(lines) + "\n"
    lines=["# CPU and GPU backends", "", "Check which compiled implementations are recorded for each operation, and which guarantee the operation advertises.", "",
           "This table describes the source-bound catalog snapshot used to build these docs. Your local build may include fewer backends. Run `graphmine-native catalog` to inspect it. Compilation, compatible inputs, and validation evidence are separate requirements. A GPU implementation can include CPU verification or bounded materialization.", "",
           "Quality can depend on parameters or the chosen backend. Read the actual result's guarantee and completeness fields. A CPU implementation is not automatically exact; a GPU implementation is not automatically approximate.", "",
           "| Operation | Problem | CPU | GPU | Quality | Supported profile / limitations |", "| --- | --- | --- | --- | --- | --- |"]
    for op in document["operations"]:
        p=next(p for p in document["problems"] if p["id"]==op["problem_id"])
        lines.append(f"| `{op['id']}` | [{p['name']}](../problem/families/{p['family']}.md#{p['id']}) | {devices(op,'cpu')} | {devices(op,'gpu')} | {quality(op)} | {cell(op['description'])} |")
    pages["library/backends.md"]="\n".join(lines)+"\n"
    anchors = [f'<span id="family/{f["id"]}"></span>' for f in document["families"]]
    anchors += [f'<span id="problem/{p["id"]}"></span>' for p in document["problems"]]
    explorer = (ROOT / "docs-src/problem/explorer.md").read_text().split("<!-- Generated catalog anchors -->")[0].rstrip()
    pages["problem/explorer.md"] = explorer + "\n\n<!-- Generated catalog anchors -->\n<div hidden>\n" + "\n".join(anchors) + "\n</div>\n"
    return pages
