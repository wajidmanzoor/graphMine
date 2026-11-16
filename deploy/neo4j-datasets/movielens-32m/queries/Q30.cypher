// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 59
CALL gds.graph.project(
  'ML32MRatingGraphLouvain',
  ['User', 'Movie'],
  {RATED: {type: 'RATED', orientation: 'UNDIRECTED'}}
);

CALL gds.louvain.stream('ML32MRatingGraphLouvain')
YIELD nodeId, communityId
RETURN communityId, count(*) AS communitySize
ORDER BY communitySize DESC;