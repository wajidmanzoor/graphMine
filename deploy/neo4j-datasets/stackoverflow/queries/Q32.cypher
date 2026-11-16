// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 97
MATCH (q:Post_question)
WHERE q.creation_date IS NOT NULL
AND q.creation_date <> ''
WITH substring(q.creation_date, 0, 4) AS year_val,
     COUNT(q) AS total_questions,
     SUM(CASE WHEN toInteger(q.answer_count) > 0 THEN 1 ELSE 0 END) AS answered_questions
RETURN year_val,
       total_questions,
       answered_questions,
round(toFloat(answered_questions) * 100.0 / toFloat(total_questions), 5) AS answer_rate
ORDER BY year_val ASC;