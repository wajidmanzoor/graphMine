// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 56

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
// Published code block: 57

CALL gds.degree.stream(
  'FriendGraph'
)
YIELD nodeId, score
WITH gds.util.asNode(nodeId) AS u, score
RETURN
  u.name AS name,
  u.user_id AS user_id,
  score AS degree
ORDER BY degree DESC
LIMIT 10;