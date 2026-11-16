// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 32
MATCH (a:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND]-(b:User),
      (a)-[:FRIEND]-(c:User),
      (a)-[:FRIEND]-(d:User),
      (b)-[:FRIEND]-(c),
      (b)-[:FRIEND]-(d),
      (c)-[:FRIEND]-(d)
WHERE b.user_id < c.user_id AND c.user_id < d.user_id
RETURN b.name AS user_b, c.name AS user_c, d.name AS user_d
LIMIT 10