// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 7

// T2.1. Persons who speak a given language and registered in a given period
MATCH (person:Person)
WHERE $language IN person.speaks
  AND person.creationDate >= $startDate
  AND person.creationDate <= $endDate
RETURN person.id AS personId,
       person.firstName AS firstName,
       person.lastName AS lastName,
       person.creationDate AS creationDate
ORDER BY creationDate DESC, personId
LIMIT $limit