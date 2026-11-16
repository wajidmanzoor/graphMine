// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 10

// T2.4. Shortest friendship path between two persons
MATCH p = shortestPath(
  (:Person {id: $person1Id})-[:KNOWS*1..6]-(:Person {id: $person2Id})
)
RETURN [n IN nodes(p) | n.id] AS personIds, length(p) AS hopCount