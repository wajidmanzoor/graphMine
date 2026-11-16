"""Resolve a dataset to its own verified Neo4j connection, without SQL mappings."""

from .analytics import AnalyticsError


def resolve_source(settings, source, dataset_id):
    from .database_datasets import selected_dataset

    if not dataset_id:
        return source
    dataset = selected_dataset(settings, source, dataset_id)
    if dataset.get("registry"):
        if (source._catalog.get("id") != dataset["id"] or source.neo4j_uri != dataset["bolt_uri"]
                or source.neo4j_password_env != dataset["password_env"]):
            raise AnalyticsError("The selected dataset connection changed. Reload it before querying.", "source_changed", 409)
    return source
