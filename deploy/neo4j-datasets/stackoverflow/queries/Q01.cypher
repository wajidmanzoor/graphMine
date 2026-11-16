// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 35
MATCH (u:User {user_id: 115218})<-[:COMMENTED_BY]-(c:Comment)
RETURN c.comment_id AS commentId, c.text AS text, c.score AS score, c.creation_date AS creationDate
ORDER BY score DESC, commentId;