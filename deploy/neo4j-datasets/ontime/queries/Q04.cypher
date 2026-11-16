// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 9
MATCH (origin:Airport {airport_id: $originAirportId})-[f:FLIGHT]->(dest:Airport)
WHERE f.Year = $year
  AND f.DepDelayMinutes >= $minDelayMinutes
RETURN dest.airport_id AS airport_id, dest.code AS code, f.FlightDate AS flight_date,
       f.IATA_CODE_Reporting_Airline AS airline, f.DepDelayMinutes AS departure_delay
ORDER BY departure_delay DESC
LIMIT $limit;