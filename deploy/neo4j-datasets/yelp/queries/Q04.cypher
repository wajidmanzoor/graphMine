// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 14
MATCH (start:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND*1..2]-(neighbor:User)
WHERE neighbor <> start
  AND neighbor.review_count >= 100
  AND neighbor.average_stars >= 4.0
RETURN DISTINCT neighbor.name AS name,
       neighbor.user_id AS user_id,
       neighbor.review_count AS review_count,
       neighbor.average_stars AS average_stars
ORDER BY review_count DESC, average_stars DESC
LIMIT 100