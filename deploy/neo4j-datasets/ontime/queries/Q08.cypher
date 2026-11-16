// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 17
MATCH (source:Airport {airport_id: $sourceAirportId})
MATCH (target:Airport {airport_id: $targetAirportId})
MATCH p = shortestPath((source)-[:FLIGHT*1..4]->(target))
RETURN p, length(p) AS hop_count;