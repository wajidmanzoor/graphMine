// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 68

MATCH (me:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND]->(f:User)
MATCH (other:User)-[:FRIEND]->(f)
WHERE other.user_id <> me.user_id
RETURN other.user_id AS user_id,
       other.name AS name,
       count(DISTINCT f.user_id) AS mutual_count
ORDER BY mutual_count DESC, user_id ASC
LIMIT 50