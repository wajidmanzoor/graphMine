"""SQL joins for the published benchmark imports, including existing stores.

These definitions describe the importer's actual foreign keys. No browser
supplied SQL or guessed Neo4j element IDs are used for source lookup.
"""

import re

from .database_sources import DatabaseSource, IDENTIFIER, source_keys


# table: (source table, target table, source column, target column, row key)
RELATIONS = {
    "movielens-32m": {
        "ratings": ("users", "movies", "userId", "movieId", ["userId", "movieId"]),
        "tags": ("users", "movies", "userId", "movieId", ["tag_id"]),
        "has_genre": ("movies", "genres", "movieId", "genre", ["movieId", "genre"]),
    },
    "yelp": {
        "wrote": ("users", "reviews", "user_id", "review_id", ["review_id"]),
        "reviews_business": ("reviews", "businesses", "review_id", "business_id", ["review_id"]),
        "tipped": ("users", "tips", "user_id", "tip_id", ["tip_id"]),
        "tip_for": ("tips", "businesses", "tip_id", "business_id", ["tip_id"]),
        "in_category": ("businesses", "categories", "business_id", "category", ["business_id", "category"]),
        "friends": ("users", "users", "src", "dst", ["src", "dst"]),
    },
    "movielens-genome": {
        "ratings": ("users", "movies", "user_id", "item_id", ["user_id", "item_id"]),
        "has_tag": ("movies", "tags", "item_id", "tag_id", ["item_id", "tag_id"]),
        "has_review": ("movies", "reviews", "item_id", "review_id", ["review_id"]),
        "answered": ("users", "surveys", "user_id", "survey_id", ["survey_id"]),
        "about_movie": ("surveys", "movies", "survey_id", "item_id", ["survey_id"]),
        "about_tag": ("surveys", "tags", "survey_id", "tag_id", ["survey_id"]),
        "directed": ("directors", "movies", "src", "dst", ["src", "dst"]),
        "acted_in": ("actors", "movies", "src", "dst", ["src", "dst"]),
    },
    "ontime": {
        "flights": ("airports", "airports", "OriginAirportID", "DestAirportID", ["flight_id"]),
    },
    "stackoverflow": {
        "earned": ("users", "badges", "user_id", "badge_id", ["badge_id"]),
        "answers_to": ("answers", "questions", "post_id", "parent_id", ["post_id"]),
        "accepts": ("questions", "answers", "post_id", "accepted_answer_id", ["post_id"]),
        "commented_by": ("comments", "users", "comment_id", "user_id", ["comment_id"]),
        "tag_to": ("tags", "questions", "tag_id", "post_id", ["tag_id", "post_id"]),
        "tags_tag_wiki": ("tags", "tag_wiki", "tag_id", "wiki_post_id", ["tag_id"]),
        "tags_tag_wiki_excerpt": ("tags", "tag_wiki_excerpt", "tag_id", "excerpt_post_id", ["tag_id"]),
        "links": ("questions", "questions", "post_id", "related_post_id", ["post_link_id"]),
    },
}
for name in ("questions", "answers", "tag_wiki", "tag_wiki_excerpt"):
    for suffix, column in (("owner", "owner_user_id"), ("editor", "last_editor_user_id")):
        RELATIONS["stackoverflow"][f"{name}_{suffix}"] = (name, "users", "post_id", column, ["post_id"])
for name in ("questions", "answers"):
    for prefix, key in (("comments", "comment_id"), ("votes", "vote_id")):
        RELATIONS["stackoverflow"][f"{prefix}_{name}"] = (prefix, name, key, "post_id", [key])


def relation_definition(dataset_id, table):
    if dataset_id != "ldbc-snb":
        return RELATIONS.get(dataset_id, {}).get(table["name"])
    parts = table["name"].split("_")
    columns = [c["name"] for c in table["columns"] if c["name"].lower().endswith("id")]
    if len(parts) != 3 or len(columns) != 2:
        return None
    aliases = {"Country": "Place", "City": "Place", "University": "Organisation", "Company": "Organisation"}
    key = columns + [c["name"] for c in table["columns"] if c["name"] in {"workFrom", "classYear"}]
    return (aliases.get(parts[0], parts[0]), aliases.get(parts[2], parts[2]), *columns, key)


def catalog_source(source, dataset):
    """Make a dataset-scoped mapping from its trusted SQL catalog manifest."""
    identifier = dataset["id"]
    if identifier not in {*RELATIONS, "ldbc-snb"} or not dataset.get("graph_label"):
        return source
    schema = dataset.get("schema_name", identifier.replace("-", "_"))
    prefix = identifier.replace("-", "_") + "_"
    entities, relationships, labels, types = [], [], {}, {}
    tables = {t["name"]: t for t in dataset.get("tables", [])}
    for table in tables.values():
        if table.get("kind") != "nodes" or not table.get("key"):
            continue
        columns = [c["name"] for c in table["columns"] if not c["name"].startswith("_gm_")]
        graph_labels = table.get("labels", [])
        own_labels = [label for label in graph_labels if label != dataset["graph_label"]]
        if not own_labels or any(not re.fullmatch(IDENTIFIER, c) for c in columns):
            continue
        mapping_id = prefix + table["name"]
        entities.append(dict(id=mapping_id, table=table["name"], schema_name=schema,
                             key=[table["key"]], label=own_labels[-1], attributes=columns,
                             display=next((c for c in ("name", "title", "firstName", "display_name") if c in columns), None)))
        labels[mapping_id] = graph_labels
        types[mapping_id] = {c["name"]: c["type"] for c in table["columns"]}
    by_table = {m["table"]: m for m in entities}
    for table in tables.values():
        if table.get("kind") != "relationships":
            continue
        definition = relation_definition(identifier, table)
        if not definition:
            continue
        start, end, start_column, end_column, key = definition
        if start not in by_table or end not in by_table:
            continue
        columns = [c["name"] for c in table["columns"] if not c["name"].startswith("_gm_")]
        if not set(key + [start_column, end_column]).issubset(columns):
            continue
        mapping_id = prefix + table["name"]
        relationships.append(dict(id=mapping_id, table=table["name"], schema_name=schema,
                                  key=key, label=table["relationship_type"], attributes=columns,
                                  source_entity=by_table[start]["id"], target_entity=by_table[end]["id"],
                                  source_columns=[start_column], target_columns=[end_column]))
        types[mapping_id] = {c["name"]: c["type"] for c in table["columns"]}
    if not entities:
        return source
    mapped = DatabaseSource.model_validate({**source.model_dump(), "entities": entities, "relationships": relationships})
    mapped._sql_credentials = source._sql_credentials
    mapped._neo4j_password = source._neo4j_password
    mapped._network_settings = source._network_settings
    mapped._config_stamp = source._config_stamp
    mapped._managed = source._managed
    mapped._catalog = {"id": identifier, "graph_label": dataset["graph_label"], "labels": labels, "types": types}
    return mapped


def resolve_source(settings, source, dataset_id):
    if not dataset_id or dataset_id == "default":
        return source
    from .database_datasets import selected_dataset
    return catalog_source(source, selected_dataset(settings, source, dataset_id))


def graph_identity(source, value, kind, node_refs):
    catalog = source._catalog
    if not catalog:
        return None

    def matches(node, mapping_id):
        return set(catalog["labels"][mapping_id]).issubset(node.labels)

    for mapping in source.entities if kind == "vertices" else source.relationships:
        props = dict(value)
        if kind == "vertices":
            if not matches(value, mapping.id):
                continue
        else:
            start = node_refs.get(value.start_node.element_id, value.start_node)
            end = node_refs.get(value.end_node.element_id, value.end_node)
            if value.type != mapping.label or not matches(start, mapping.source_entity) or not matches(end, mapping.target_entity):
                continue
            for node, alias, columns in ((start, mapping.source_entity, mapping.source_columns),
                                         (end, mapping.target_entity, mapping.target_columns)):
                for column, key in zip(columns, source.mapping(alias).key):
                    # LDBC endpoint columns are import-only, so use the original
                    # endpoint key retained in the graph, never its element ID.
                    props.setdefault(column, node.get(key))
        keys = [props.get(key) for key in mapping.key]
        if any(type(v) not in (str, int, float, bool) for v in keys):
            continue
        return mapping, source_keys(source, mapping, keys)
    return None
