// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 15
MATCH p = (:Airport {airport_id: $sourceAirportId})-[:FLIGHT*1..3]->(:Airport {airport_id: $targetAirportId})
RETURN count(p) > 0 AS reachable
LIMIT 1;