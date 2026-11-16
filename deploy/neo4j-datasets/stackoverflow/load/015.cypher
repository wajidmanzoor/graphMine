// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 20
CALL apoc.periodic.iterate(
    "
    MATCH (pq:Post_question)
    WHERE pq.last_editor_user_id IS NOT NULL
      AND pq.last_editor_user_id <> 0
    RETURN
        pq.post_id AS question_id,
        pq.last_editor_user_id AS editor_user_id
    ",
    "
    MATCH (pq:Post_question {post_id: question_id})
    MATCH (u:User {user_id: editor_user_id})
    MERGE (pq)-[:LAST_EDITED_BY]->(u)
    ",
    {
        batchSize: 20000,
        parallel: false,
        retries: 2
    }
);