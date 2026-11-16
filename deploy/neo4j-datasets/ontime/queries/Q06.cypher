// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 13
MATCH (origin:Airport)-[f:FLIGHT]->(dest:Airport)
WHERE f.Year = $year
  AND f.Cancelled = 0
  AND f.Distance >= $minDistance
RETURN origin.code AS origin, dest.code AS dest, f.FlightDate AS flight_date,
       f.IATA_CODE_Reporting_Airline AS airline, f.Distance AS distance
ORDER BY distance DESC
LIMIT $limit;