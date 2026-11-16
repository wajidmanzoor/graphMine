// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 8

// T2.2. Friendship edges created within a given window
MATCH (person1:Person)-[knows:KNOWS]->(person2:Person)
WHERE knows.creationDate >= $startDate
  AND knows.creationDate <= $endDate
RETURN person1.id AS person1Id,
       person2.id AS person2Id,
       knows.creationDate AS creationDate
ORDER BY creationDate, person1Id
LIMIT $limit