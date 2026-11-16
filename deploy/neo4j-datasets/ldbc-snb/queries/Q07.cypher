// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 9

// T2.3. Whether two persons are connected within four friendship hops
MATCH (source:Person {id: $person1Id}),
      (target:Person {id: $person2Id})
RETURN EXISTS {
  MATCH (source)-[:KNOWS*1..4]-(target)
} AS reachable