// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 57
CALL gds.graph.project(
  'ML32MRatingGraphPageRank',
  ['User', 'Movie'],
  {RATED: {type: 'RATED', orientation: 'UNDIRECTED'}}
);

CALL gds.pageRank.stream('ML32MRatingGraphPageRank')
YIELD nodeId, score
RETURN labels(gds.util.asNode(nodeId)) AS labels,
       coalesce(gds.util.asNode(nodeId).userId, gds.util.asNode(nodeId).movieId) AS id,
       gds.util.asNode(nodeId).title AS title,
       score
ORDER BY score DESC;