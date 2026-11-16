// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 19
MATCH p = (:Airport {airport_id: $sourceAirportId})-[:FLIGHT*1..3]->(:Airport {airport_id: $targetAirportId})
WHERE all(n IN nodes(p) WHERE single(m IN nodes(p) WHERE m = n))
RETURN p, length(p) AS hop_count
ORDER BY hop_count
LIMIT $limit;