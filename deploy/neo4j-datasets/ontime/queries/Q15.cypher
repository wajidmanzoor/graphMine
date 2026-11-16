// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 31
MATCH (source:Airport {airport_id: $sourceAirportId})-[first:FLIGHT]->(middle:Airport)-[second:FLIGHT]->(dest:Airport)
WHERE first.Year = $year
  AND second.Year = $year
  AND source <> dest
RETURN middle.code AS connection_airport, dest.code AS destination, count(*) AS connection_count
ORDER BY connection_count DESC
LIMIT $limit;