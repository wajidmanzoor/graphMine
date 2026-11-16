// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 39
MATCH (:Airport)-[f:FLIGHT]->(:Airport)
WHERE f.Year = $year
RETURN count(f) AS flight_count,
       avg(f.Distance) AS avg_distance,
       min(f.Distance) AS min_distance,
       max(f.Distance) AS max_distance,
       avg(f.ArrDelayMinutes) AS avg_arrival_delay;