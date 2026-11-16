// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 26
MATCH (a:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND]-(b:User),
      (b)-[:FRIEND]-(c:User),
      (c)-[:FRIEND]-(a)
WHERE a <> b AND b <> c AND a <> c
RETURN DISTINCT b.name AS friend_one, c.name AS friend_two
LIMIT 25