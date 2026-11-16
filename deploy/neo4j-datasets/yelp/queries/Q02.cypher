// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 10
MATCH (start:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND*1..2]-(neighbor:User)
WHERE neighbor <> start
RETURN DISTINCT neighbor.name AS name, neighbor.user_id AS user_id
ORDER BY name, user_id
LIMIT 100