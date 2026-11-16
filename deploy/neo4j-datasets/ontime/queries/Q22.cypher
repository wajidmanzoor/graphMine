// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 45
MATCH p = (:Airport {airport_id: $sourceAirportId})-[:FLIGHT*1..3]->(target:Airport)
RETURN length(p) AS path_length,
       target.state AS target_state,
       count(p) AS path_count,
       count(DISTINCT target) AS distinct_target_count
ORDER BY path_length, path_count DESC
LIMIT $limit;