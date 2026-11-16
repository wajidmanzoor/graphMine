// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 3

// T1.1. One-hop friends of a given person
MATCH (:Person {id: $personId})-[:KNOWS]-(friend:Person)
RETURN friend.id AS personId, friend.firstName AS firstName, friend.lastName AS lastName
ORDER BY personId
LIMIT $limit