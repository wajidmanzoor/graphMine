// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 67
MATCH (c:Comment)-[:COMMENTED_BY]->(u:User)
WITH u.user_id AS user_id,
     u.display_name AS display_name,
     COUNT(c) AS total_comments
WHERE total_comments > 0
RETURN user_id, display_name, total_comments
ORDER BY total_comments DESC
LIMIT 100;