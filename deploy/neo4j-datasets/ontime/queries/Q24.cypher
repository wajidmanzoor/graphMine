// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 49
MATCH (airport:Airport)-[:FLIGHT]-(neighbor:Airport)
RETURN airport.airport_id AS airport_id, airport.code AS code, airport.city AS city,
       count(DISTINCT neighbor) AS degree
ORDER BY degree DESC
LIMIT $limit;