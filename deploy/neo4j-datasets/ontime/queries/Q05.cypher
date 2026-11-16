// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 11
MATCH (airport:Airport)
WHERE airport.state = $state
  AND airport.code STARTS WITH $codePrefix
RETURN airport.airport_id AS airport_id, airport.code AS code, airport.city AS city, airport.stateName AS state_name
ORDER BY code
LIMIT $limit;