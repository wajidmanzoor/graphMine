// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 7
MATCH p = (:Airport {airport_id: $originAirportId})-[f:FLIGHT*3]->(dest:Airport)
WHERE all(flight IN f WHERE flight.year = $Year)
RETURN DISTINCT dest.airport_id AS airport_id, dest.code AS code, dest.city AS city, length(p) AS hop_count
ORDER BY code
LIMIT $limit;