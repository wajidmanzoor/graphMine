// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 20

// T3.2. Friendship squares around a given person
MATCH (a:Person {id: $personId})-[:KNOWS]-(b:Person),
      (b)-[:KNOWS]-(c:Person),
      (c)-[:KNOWS]-(d:Person),
      (d)-[:KNOWS]-(a)
WHERE a <> b AND a <> c AND a <> d
  AND b <> c AND b <> d AND c <> d
RETURN DISTINCT b.id AS firstFriendId, c.id AS bridgeFriendId, d.id AS secondFriendId
LIMIT $limit