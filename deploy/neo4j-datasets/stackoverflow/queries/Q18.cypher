// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 69
MATCH (t:Tag)-[:TAG_TO]->(q:Post_question)
OPTIONAL MATCH (q)<-[:ANSWERS_TO]-(a:Post_answer)
RETURN t.tag_name AS tagName,
       count(DISTINCT q) AS questionCount,
       count(a) AS answerCount,
       avg(coalesce(q.score, 0)) AS avgQuestionScore
ORDER BY questionCount DESC;