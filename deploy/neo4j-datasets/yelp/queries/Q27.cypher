// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 60

CALL gds.graph.project(
  'FriendGraph',
  'User',
  {
    FRIEND: {
      type: 'FRIEND',
      orientation: 'UNDIRECTED'
    }
  }
)
YIELD graphName, nodeCount, relationshipCount, projectMillis
RETURN graphName, nodeCount, relationshipCount, projectMillis;

// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 61

CALL gds.wcc.stream('FriendGraph')
YIELD nodeId, componentId
WITH componentId, count(*) AS component_size
RETURN componentId, component_size
ORDER BY component_size DESC
LIMIT 10;