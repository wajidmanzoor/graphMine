// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 41
MATCH (origin:Airport)-[f:FLIGHT]->(dest:Airport)
WHERE f.Year = $year
RETURN origin.state AS origin_state,
       dest.state AS dest_state,
       count(f) AS flight_count,
       avg(f.Distance) AS avg_distance,
       avg(f.ArrDelayMinutes) AS avg_arrival_delay
ORDER BY flight_count DESC
LIMIT $limit;