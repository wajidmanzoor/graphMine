// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 77
MATCH (q:Post_question)
OPTIONAL MATCH (q)-[:LINK_TO]-(neighbor:Post_question)
RETURN q.post_id AS questionId,
       q.title AS title,
       count(DISTINCT neighbor) AS linkDegree
ORDER BY linkDegree DESC
LIMIT 100;