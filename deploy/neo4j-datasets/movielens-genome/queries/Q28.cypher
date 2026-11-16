// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 63
CALL gds.graph.project(
  'MLGenomeRatingGraphWcc',
  ['User', 'Movie'],
  {RATED: {type: 'RATED', orientation: 'UNDIRECTED'}}
);

CALL gds.wcc.stream('MLGenomeRatingGraphWcc')
YIELD nodeId, componentId
RETURN componentId, count(*) AS ComponentSize
ORDER BY ComponentSize DESC