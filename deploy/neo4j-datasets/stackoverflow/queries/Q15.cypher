// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 63
MATCH (q:Post_question)
OPTIONAL MATCH (q)<-[:ANSWERS_TO]-(a:Post_answer)
WITH q, count(DISTINCT a) AS answerDegree
RETURN count(q) AS questionCount,
       avg(answerDegree) AS avgAnswerDegree,
       min(answerDegree) AS minAnswerDegree,
       max(answerDegree) AS maxAnswerDegree;