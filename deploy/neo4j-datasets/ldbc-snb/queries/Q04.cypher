// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 6

// T1.4. Persons within two friendship hops who speak a given language
MATCH (start:Person {id: $personId})-[:KNOWS*1..2]-(neighbor:Person)
WHERE neighbor <> start
  AND $language IN neighbor.speaks
  AND neighbor.birthday >= $birthday
RETURN DISTINCT neighbor.id AS personId,
       neighbor.firstName AS firstName,
       neighbor.lastName AS lastName,
       neighbor.birthday AS birthday
ORDER BY birthday DESC, personId
LIMIT $limit