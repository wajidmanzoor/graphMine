// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 64

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
// Published code block: 65

CALL gds.louvain.stream('FriendGraph')
YIELD nodeId, communityId
WITH communityId, count(*) AS size
RETURN communityId, size
ORDER BY size DESC
LIMIT 10;