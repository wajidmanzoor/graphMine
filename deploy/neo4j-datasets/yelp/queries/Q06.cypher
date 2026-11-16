// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 18

MATCH (u:User)-[:WROTE]->(r:Review)-[:REVIEWS]->(b:Business)
WHERE r.stars = 5
  AND r.useful >= 10
RETURN u.name AS user_name,
       r.id AS review_id,
       r.stars AS stars,
       r.useful AS useful_votes,
       b.name AS business_name,
       b.city AS city
ORDER BY useful_votes DESC
LIMIT 20