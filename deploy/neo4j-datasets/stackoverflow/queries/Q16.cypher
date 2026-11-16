// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 65
MATCH (src:Post_question)-[:LINK_TO]->(target:Post_question)
WITH target.post_id   AS question_id,
     COUNT(src)  AS link_count
WHERE link_count > 0
RETURN question_id, link_count
ORDER BY link_count DESC
LIMIT 100;