// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 11

// T2.5. All simple friendship paths between two persons up to length three
MATCH p = (:Person {id: $person1Id})-[:KNOWS*1..3]-(:Person {id: $person2Id})
WHERE all(i IN range(0, size(nodes(p)) - 1)
          WHERE single(n IN nodes(p) WHERE n = nodes(p)[i]))
RETURN [n IN nodes(p) | n.id] AS personIds, length(p) AS hopCount
ORDER BY hopCount ASC
LIMIT $limit