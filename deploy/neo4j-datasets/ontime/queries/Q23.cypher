// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 47
MATCH (origin:Airport)-[:FLIGHT]->(destA:Airport {state: $stateA})
MATCH (origin)-[:FLIGHT]->(destB:Airport {state: $stateB})
RETURN DISTINCT origin.airport_id AS airport_id, origin.code AS code, origin.city AS city, origin.state AS state
ORDER BY code
LIMIT $limit;