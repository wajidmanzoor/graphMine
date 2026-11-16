// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 28
CALL apoc.periodic.iterate(
    "
    MATCH (c:Comment)
    WHERE c.post_id IS NOT NULL
      AND c.post_id <> 0
    RETURN
        c.comment_id AS comment_id,
        c.post_id AS question_id
    ",
    "
    MATCH (c:Comment {comment_id: comment_id})
    MATCH (pq:Post_question {post_id: question_id})
    MERGE (c)-[:ON_QUESTION]->(pq)
    ",
    {
        batchSize: 20000,
        parallel: false,
        retries: 2
    }
);