// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 89
MATCH (q:Post_question)-[:ACCEPTS]->(a:Post_answer)-[:ANSWERS_BY]->(u:User)
WITH u.user_id AS user_id,
     u.display_name AS display_name,
     COUNT(a) AS accepted_count
WHERE accepted_count > 0
RETURN user_id, display_name, accepted_count
ORDER BY accepted_count DESC
LIMIT 100;