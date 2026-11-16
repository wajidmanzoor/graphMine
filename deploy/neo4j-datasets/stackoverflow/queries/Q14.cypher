// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 61
MATCH (questioner:User)<-[:OWNED_BY]-(q:Post_question)<-[:ANSWERS_TO]-(a:Post_answer)<-[:ON_ANSWER]-(c:Comment)-[:COMMENTED_BY]->(commenter:User)
WHERE questioner.user_id <> commenter.user_id
RETURN questioner.user_id AS questionerId, q.post_id AS questionId, a.post_id AS answerId,
       c.comment_id AS commentId, commenter.user_id AS commenterId;