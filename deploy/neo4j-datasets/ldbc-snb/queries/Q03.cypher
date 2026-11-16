// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 5

// T1.3. Persons exactly three friendship hops away
MATCH (start:Person {id: $personId})-[:KNOWS*3]-(neighbor:Person)
WHERE neighbor <> start
RETURN DISTINCT neighbor.id AS personId, neighbor.firstName AS firstName, neighbor.lastName AS lastName
ORDER BY personId
LIMIT $limit