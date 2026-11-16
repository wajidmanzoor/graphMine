// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 58
CALL gds.graph.project(
  'ML32MRatingGraphWcc',
  ['User', 'Movie'],
  {RATED: {type: 'RATED', orientation: 'UNDIRECTED'}}
);

CALL gds.wcc.stream('ML32MRatingGraphWcc')
YIELD nodeId, componentId
RETURN componentId, count(*) AS componentSize
ORDER BY componentSize DESC;