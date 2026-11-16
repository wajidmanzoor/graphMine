// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 12

MATCH (start:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND*3]-(neighbor)
WHERE neighbor.user_id <> "Oi1qbcz2m2SnwUeztGYcnQ"
RETURN DISTINCT neighbor.name, neighbor.user_id