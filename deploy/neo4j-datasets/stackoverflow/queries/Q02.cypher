// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 37
MATCH p = (s:Post_question {post_id: 26615966})-[:LINK_TO*1..2]->(n:Post_question)
RETURN DISTINCT n.post_id AS questionId, n.title AS title, n.score AS score
ORDER BY questionId
LIMIT 100;