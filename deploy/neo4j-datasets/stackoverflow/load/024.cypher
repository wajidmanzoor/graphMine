// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 29
CALL apoc.periodic.iterate(
    "
    MATCH (c:Comment)
    WHERE c.post_id IS NOT NULL
      AND c.post_id <> 0
    RETURN
        c.comment_id AS comment_id,
        c.post_id AS answer_id
    ",
    "
    MATCH (c:Comment {comment_id: comment_id})
    MATCH (pa:Post_answer {post_id: answer_id})
    MERGE (c)-[:ON_ANSWER]->(pa)
    ",
    {
        batchSize: 20000,
        parallel: false,
        retries: 2
    }
);