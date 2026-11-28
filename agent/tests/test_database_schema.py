"""Read-only dataset schema respects properties and authorization."""

from test_database_workspace import source, workspace  # noqa: F401


def test_schema_exposes_graph_properties_and_requires_access(workspace):
    client = workspace.client
    path = "/api/database-sources/demo/schema"
    response = client.get(path)
    assert response.status_code == 200, response.text
    schema = response.json()
    assert [p["name"] for p in schema["entities"][0]["properties"]] == ["name"]
    assert [p["name"] for p in schema["relationships"][0]["properties"]] == ["amount"]
    assert schema["relationships"][0]["source_entity"] == "accounts"
    assert client.get(path, params={"dataset_id": "unrelated-dataset"}).status_code == 404
    assert client.get(path, headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/database-sources/private/schema").status_code == 404



def test_catalog_diagram_includes_labels_missing_from_a_global_sample(source, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from neo4j.graph import Graph, Node
    from graphmine_agent.neo4j_schema import diagram_schema
    g = Graph()
    a, b = Node(g,'a',1,{'Review'},{'name':'Review'}), Node(g,'b',2,{'RareLabel'},{'name':'RareLabel'})
    edge = g.relationship_type('LINK')(g,'e',3,{})
    edge._start_node, edge._end_node = a,b
    queries=[]
    class Tx:
        def run(self, statement, parameters):
            queries.append(statement)
            if statement.startswith('CALL'):
                return [{'nodes':[a,b],'relationships':[edge]}]
            return [{'properties':['text','gm_internal']}]
    @contextmanager
    def session(_):
        yield SimpleNamespace()
    monkeypatch.setattr('graphmine_agent.neo4j_schema.neo4j_session',session)
    monkeypatch.setattr('graphmine_agent.neo4j_schema.neo4j_read',lambda session,source,read,**kwargs:read(Tx()))
    value=diagram_schema(source)
    assert [item['label'] for item in value['entities']]==['Review','RareLabel']
    assert value['relationships'][0]['source_entity']=='label:Review'
    assert value['relationships'][0]['target_entity']=='label:RareLabel'
    assert value['entities'][0]['properties']==[{'name':'text','type':''}]
    assert value['schema_scope']['complete_labels'] and value['schema_scope']['sampled_properties']
    assert all('LIMIT 8' in q for q in queries if not q.startswith('CALL'))


def test_diagram_fallback_discloses_incomplete_schema(source, monkeypatch):
    from contextlib import contextmanager
    from graphmine_agent.neo4j_schema import diagram_schema
    @contextmanager
    def unavailable(_):
        raise RuntimeError('catalog unavailable')
        yield
    monkeypatch.setattr('graphmine_agent.neo4j_schema.neo4j_session',unavailable)
    monkeypatch.setattr('graphmine_agent.neo4j_schema.sample_schema',lambda _: {'entities':[], 'relationships':[], 'message':'Bounded sample', 'schema_scope':{'complete':False}})
    value=diagram_schema(source)
    assert value['schema_scope']['complete'] is False
    assert value['message']=='Full catalog access is unavailable. Bounded sample'
