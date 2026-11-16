// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 22

// T3.4. Groups of four mutually acquainted persons around a given person
MATCH (a:Person {id: $personId})-[:KNOWS]-(b:Person),
      (a)-[:KNOWS]-(c:Person),
      (a)-[:KNOWS]-(d:Person),
      (b)-[:KNOWS]-(c),
      (b)-[:KNOWS]-(d),
      (c)-[:KNOWS]-(d)
WHERE b.id < c.id AND c.id < d.id
RETURN b.id AS person2Id, c.id AS person3Id, d.id AS person4Id
LIMIT $limit