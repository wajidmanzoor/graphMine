"""One authorized, metadata-only inventory for query and import sources."""

from fastapi import Request

from .analytics import AnalyticsError
from .identity import AccountError, current_principal


def discover(runtime):
    from .connectors import available as connectors
    from .database_sources import available as databases

    items, warnings = [], []
    for provider, read in (("database", lambda: databases(runtime.settings)), ("connector", lambda: connectors(runtime))):
        try:
            sources = read()
        except (AnalyticsError, AccountError) as error:
            warnings.append({"provider": provider, "code": error.code,
                             "message": "Database connections could not be listed." if provider == "database" else "Import connections could not be listed."})
            continue
        for source in sources:
            item = {"id": f"{provider}:{source.id}", "source_id": source.id,
                    "provider": provider, "name": source.name, "managed": source.managed}
            if provider == "database":
                item.update(type="neo4j", capabilities=source.capabilities(), connection=source.public())
            else:
                item.update(type=source.type, capabilities={"cypher": False, "preview": True, "import": True,
                            "enrichment": False, "expansion": False, "sync": False})
            items.append(item)
    items.sort(key=lambda item: (item["name"].casefold(), item["id"]))
    return {"items": items, "warnings": warnings, "can_manage_imports": current_principal.get() is not None}


def register_source_routes(router):
    @router.get("/data-sources")
    def inventory(request: Request):
        return discover(request.app.state.runtime)
