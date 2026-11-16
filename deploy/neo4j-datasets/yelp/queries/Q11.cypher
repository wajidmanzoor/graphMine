// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 28
MATCH (a:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND]-(b:User),
      (b)-[:FRIEND]-(c:User),
      (c)-[:FRIEND]-(d:User),
      (d)-[:FRIEND]-(a)
WHERE a <> b AND a <> c AND a <> d
  AND b <> c AND b <> d AND c <> d
RETURN DISTINCT b.name AS first_friend, c.name AS bridge_friend, d.name AS second_friend
LIMIT 25