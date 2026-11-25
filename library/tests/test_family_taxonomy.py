"""Taxonomy coverage and the strict gate for migrating family identifiers."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = runpy.run_path(str(ROOT / "tools/validate_families.py"))


@pytest.fixture
def taxonomy():
    return runpy.run_path(str(ROOT / "tools/family_catalog.py"))["taxonomy"](ROOT)


def errors(document):
    return VALIDATOR["validate_taxonomy"](document, VALIDATOR["registry_problems"](ROOT))


def test_every_registry_problem_belongs_to_exactly_one_valid_family(taxonomy):
    assert errors(taxonomy) == []

def test_generated_family_metadata_and_problem_categories_match_the_authoritative_source():
    subprocess.run(
        [sys.executable, str(ROOT / "tools/generate_families.py"), "--check"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )


def test_every_problem_category_matches_its_registered_problems(taxonomy):
    families = {
        problem: family["id"]
        for family in taxonomy["families"]
        for problem in family["problems"]
    }
    cards = VALIDATOR["registry_cards"](ROOT)
    specifications = [
        json.loads(path.read_text()) for path in (ROOT / "problems").glob("*/problem.json")
    ]
    assert len(specifications) == len({spec["topic_id"] for spec in specifications}) == 70
    for specification in specifications:
        assigned = {
            families[problem]
            for problem, topic in cards
            if topic == specification["topic_id"]
        }
        assert assigned == {specification["category"]}, specification["topic_id"]


def test_topic_hints_do_not_impose_an_executable_group(taxonomy, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    generator = runpy.run_path(str(ROOT / "tools/generate_families.py"))
    membership = generator["problem_family_ids"](taxonomy)
    assert set(membership) == set(VALIDATOR["registry_problems"](ROOT))
    assert membership["triangle-counting"] == "motifs"


def test_category_sync_preserves_embedded_parameters_and_names(tmp_path, taxonomy, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    import sync_problem_contracts

    monkeypatch.setattr(sync_problem_contracts, "ROOT", tmp_path)
    previous, selected = [family["id"] for family in taxonomy["families"][:2]]
    embedded = {
        "topic_id": "example", "name": "Existing name", "category": previous,
        "problem_inputs": [{"name": "scale", "default": 1}],
    }
    specification = {
        **embedded, "name": "Unrelated name edit", "category": selected,
        "problem_inputs": [{"name": "scale", "default": 1.0}],
    }
    source = tmp_path / "problems/example/problem.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(specification))
    copies = [
        ("graphmine_catalog.json", "topics"),
        ("library/manifests/graphmine_catalog.json", "topics"),
        ("graphmine_manifest.json", "included_topic_specs"),
        ("library/manifests/graphmine_manifest.json", "included_topic_specs"),
    ]
    for relative, collection in copies:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            collection: [{"source": "problems/example/problem.json", "spec": embedded}],
            "topic_index": {"example": {"name": embedded["name"], "category": previous}},
        }))
    assert len(sync_problem_contracts.synchronize(write=True, category_only=True)) == 4
    for relative, collection in copies:
        document = json.loads((tmp_path / relative).read_text())
        actual = document[collection][0]["spec"]
        assert actual == {**embedded, "category": selected}
        assert type(actual["problem_inputs"][0]["default"]) is int
        assert document["topic_index"]["example"] == {"name": embedded["name"], "category": selected}
    assert sync_problem_contracts.synchronize(category_only=True) == []


@pytest.mark.parametrize("same_family", [True, False])
def test_duplicate_membership_is_rejected(taxonomy, same_family):
    first, second = taxonomy["families"][:2]
    destination = first if same_family else second
    destination["problems"].append(first["problems"][0])
    assert any("Problems assigned more than once" in error for error in errors(taxonomy))


def test_missing_and_unknown_problem_ids_are_rejected(taxonomy):
    members = taxonomy["families"][0]["problems"]
    members[0] += "-unregistered"
    failures = errors(taxonomy)
    assert any("Missing registry problems" in error for error in failures)
    assert any("Unknown problem IDs" in error for error in failures)


@pytest.mark.parametrize("size", [1, 11])
def test_family_size_bounds_are_enforced(taxonomy, size):
    family = taxonomy["families"][0]
    family["problems"] = (family["problems"] * 2)[:size]
    assert any("between 2 and 10" in error for error in errors(taxonomy))


def test_duplicate_family_ids_are_rejected(taxonomy):
    taxonomy["families"][1]["id"] = taxonomy["families"][0]["id"]
    assert any("Duplicate family IDs" in error for error in errors(taxonomy))


def test_deciding_question_is_part_of_the_description(taxonomy):
    taxonomy["families"][0]["description"] = "A description with no deciding question."
    assert any("description must include the deciding question" in error for error in errors(taxonomy))


@pytest.mark.parametrize("root_alias", [True, False])
def test_aliases_are_not_allowed(taxonomy, root_alias):
    destination = taxonomy if root_alias else taxonomy["families"][0]
    destination["aliases"] = []
    assert any("aliases are not allowed" in error for error in errors(taxonomy))


@pytest.mark.parametrize("kind", [
    "call", "keyword", "comparison", "routing", "json", "native-card",
    "python-card", "topic-category", "markdown", "html", "html-attribute", "label-map", "link",
    "family-set", "family-membership", "family-get",
])
def test_reference_scan_rejects_unknown_families(tmp_path, taxonomy, kind):
    unknown = "obsolete_" + "family"
    problem = taxonomy["families"][0]["problems"][0]
    topic = VALIDATOR["registry_cards"](ROOT)[-1][1]
    examples = {
        "call": (".py", f"library.family({unknown!r})"),
        "keyword": (".py", f"request(family_id={unknown!r})"),
        "comparison": (".js", f"if (family.id === {unknown!r}) {{}}"),
        "routing": (".py", f"FAMILIES = (({unknown!r}, 'Title', 'Question', {{{unknown!r}}}),)"),
        "family-set": (".py", f"SEARCH_FAMILIES = {{{unknown!r}}}"),
        "family-membership": (".py", f"if card.get('family') in {{{unknown!r}}}: pass"),
        "family-get": (".py", f"if card.get('family') == {unknown!r}: pass"),
        "json": (".json", json.dumps({"families": [{"id": unknown}]})),
        "native-card": (".json", json.dumps({"id": problem, "family": unknown})),
        "python-card": (".py", f"card = {dict(id=problem, family=unknown)!r}"),
        "topic-category": (".json", json.dumps({"topic_id": topic, "graph_input": {}, "category": unknown})),
        "markdown": (".md", f"| Problem | Family |\n| --- | --- |\n| example | {unknown} |\n"),
        "html": (".html", f'<span>"family"</span>: <span>"{unknown}"</span>'),
        "html-attribute": (".html", f'<button data-family="{unknown}">Choose</button>'),
        "label-map": (".js", "const title = (family) => ({" + unknown + ": 'Title'})[family.id];"),
        "link": (".md", f"[Family](#family/{unknown})"),
    }
    suffix, source = examples[kind]
    (tmp_path / f"caller{suffix}").write_text(source)
    valid = {row["id"] for row in taxonomy["families"]}
    failures = VALIDATOR["invalid_family_references"](tmp_path, valid)
    assert failures and all(unknown in failure for failure in failures)


def test_reference_scan_allows_current_ids_and_ordinary_algorithm_terms(tmp_path, taxonomy):
    family = taxonomy["families"][0]["id"]
    (tmp_path / "caller.py").write_text(f"library.family({family!r})\n")
    (tmp_path / "notes.md").write_text("Graph traversal, matching and coloring are algorithm terms.\n")
    (tmp_path / "config.json").write_text(json.dumps({
        "family": family,
        "families": [{"id": row["id"]} for row in taxonomy["families"]],
    }))
    valid = {row["id"] for row in taxonomy["families"]}
    assert VALIDATOR["invalid_family_references"](tmp_path, valid) == []


def test_reference_scan_allows_dataset_families_and_stage_names(tmp_path, taxonomy):
    problem = taxonomy["families"][0]["problems"][0]
    (tmp_path / "data.json").write_text(json.dumps({
        "examples": [{"id": "example-1", "problem_id": problem, "family": "random"}],
        "families": ["source:example", "synthetic:example"],
    }))
    (tmp_path / "caller.py").write_text(
        "stages = ['family', 'problem', 'plan']\n"
        "fields = ['behavior', 'family', 'problem_id']\n"
        "def generate(family):\n"
        "    if family in {'random', 'cycle'}: return family\n"
    )
    valid = {row["id"] for row in taxonomy["families"]}
    assert VALIDATOR["invalid_family_references"](tmp_path, valid) == []


def test_repository_has_no_retired_family_identifiers(taxonomy):
    # This is strict throughout the migration: Steps 2–5 must remove each finding.
    # Do not xfail it or add exceptions for obsolete callers to make Step 1 green.
    valid = {row["id"] for row in taxonomy["families"]}
    failures = VALIDATOR["invalid_family_references"](ROOT, valid)
    assert not failures, (
        f"{len(failures)} family references still need migration:\n"
        + "\n".join(failures[:60])
    )
