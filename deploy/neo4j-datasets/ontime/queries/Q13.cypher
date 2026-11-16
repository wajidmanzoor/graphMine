// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 27
MATCH (center:Airport)-[f:FLIGHT]->(dest:Airport)
WHERE f.Year = $year
WITH center, count(DISTINCT dest) AS destination_count
WHERE destination_count >= $minDegree
RETURN center.airport_id AS airport_id, center.code AS code, center.city AS city, destination_count
ORDER BY destination_count DESC
LIMIT $limit;