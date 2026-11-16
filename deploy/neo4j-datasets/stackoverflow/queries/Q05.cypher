// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 43
MATCH (q:Post_question)
WHERE (q.accepted_answer_id IS NULL
    OR q.accepted_answer_id = ''
    OR q.accepted_answer_id = '0'
    OR q.accepted_answer_id = 'None')
RETURN q.post_id                                  AS question_id,
       toInteger(q.view_count)                AS view_count,
       toInteger(q.answer_count)              AS answer_count
ORDER BY toInteger(q.view_count) DESC
LIMIT 100;