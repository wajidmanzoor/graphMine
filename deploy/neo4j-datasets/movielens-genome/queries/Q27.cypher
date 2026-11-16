// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 62
CALL gds.graph.project(
  'MLGenomeRatingGraphPageRank',
  ['User', 'Movie'],
  {RATED: {type: 'RATED', orientation: 'UNDIRECTED'}}
);

CALL gds.pageRank.stream('MLGenomeRatingGraphPageRank')
YIELD nodeId, score
RETURN labels(gds.util.asNode(nodeId)) AS Labels,
       coalesce(gds.util.asNode(nodeId).title, toString(gds.util.asNode(nodeId).user_id)) AS Node,
       score
ORDER BY score DESC