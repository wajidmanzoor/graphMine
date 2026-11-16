// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 39

CALL gds.graph.project(
  'KnowsDirectedGraph',
  'Person',
  {
    KNOWS: {
      type: 'KNOWS',
      orientation: 'NATURAL'
    }
  }
)
YIELD graphName, nodeCount, relationshipCount, projectMillis
RETURN graphName, nodeCount, relationshipCount, projectMillis;

// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 40

CALL gds.scc.stream('KnowsDirectedGraph')
YIELD nodeId, componentId
RETURN componentId, count(*) AS componentSize
ORDER BY componentSize DESC
LIMIT 10;