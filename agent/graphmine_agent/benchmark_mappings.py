"""Resolve a dataset to its own verified Neo4j connection, without SQL mappings."""

from .analytics import AnalyticsError
from .neo4j_backend import matches_registry


def resolve_source(settings, source, dataset_id):
    from .database_datasets import selected_dataset

    if not dataset_id:
        return source
    dataset = selected_dataset(settings, source, dataset_id)
    if dataset.get("registry"):
        if source._catalog.get("id") != dataset["id"] or not matches_registry(source, dataset):
            raise AnalyticsError("The selected dataset connection changed. Reload it before querying.", "source_changed", 409)
    return source
