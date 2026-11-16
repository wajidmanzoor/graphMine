// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 64
CALL gds.graph.project(
  'MLGenomeRatingGraphLouvain',
  ['User', 'Movie'],
  {RATED: {type: 'RATED', orientation: 'UNDIRECTED'}}
);

CALL gds.louvain.stream('MLGenomeRatingGraphLouvain')
YIELD nodeId, communityId
RETURN communityId, count(*) AS CommunitySize
ORDER BY CommunitySize DESC