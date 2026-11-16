// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 93
MATCH (t:Tag)-[:TAG_TO]->(q:Post_question)
WITH t, COUNT(q) AS question_count
MATCH (t)-[:TAG_TO]->(q2:Post_question)<-[:ANSWERS_TO]-(a:Post_answer)
WITH t.tag_name AS tag_name,
    question_count,
    COUNT(a) AS answer_count
WHERE answer_count > 0
RETURN tag_name,
    question_count,
    answer_count,
    toFloat(question_count) / toFloat(answer_count) AS ratio
ORDER BY ratio DESC
LIMIT 100;