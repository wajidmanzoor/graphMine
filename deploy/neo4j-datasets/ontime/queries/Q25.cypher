// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 50
CALL gds.graph.project(
  'OnTimeAirportGraph',
  'Airport',
  {FLIGHT: {type: 'FLIGHT', orientation: 'NATURAL'}}
);

CALL gds.pageRank.stream('OnTimeAirportGraph')
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).airport_id AS airport_id,
       gds.util.asNode(nodeId).code AS code,
       score
ORDER BY score DESC
LIMIT $limit;