// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 32

// T4.7. Persons interested in both of two given tags
MATCH (person:Person)-[:HAS_INTEREST]->(:Tag {name: $tagA})
MATCH (person)-[:HAS_INTEREST]->(:Tag {name: $tagB})
RETURN DISTINCT person.id AS personId,
       person.firstName AS firstName,
       person.lastName AS lastName
ORDER BY personId
LIMIT $limit