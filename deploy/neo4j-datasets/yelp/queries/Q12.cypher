// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 30
MATCH (center:User)-[:FRIEND]->(friend:User)
WHERE friend.review_count >= 100
RETURN center.name AS center_name,
       center.user_id AS center_id,
       count(friend) AS prolific_friend_count
ORDER BY prolific_friend_count DESC
LIMIT 25