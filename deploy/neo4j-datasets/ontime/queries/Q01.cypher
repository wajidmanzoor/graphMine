// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 3
MATCH (origin:Airport {airport_id: $originAirportId})-[f:FLIGHT]->(dest:Airport)
WHERE f.Year = $year
RETURN DISTINCT dest.airport_id AS airport_id, dest.code AS code, dest.city AS city, dest.state AS state
ORDER BY code
LIMIT $limit;