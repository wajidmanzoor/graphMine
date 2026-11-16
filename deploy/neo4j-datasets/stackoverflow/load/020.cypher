// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 25
CALL apoc.periodic.iterate(
    "
    MATCH (pa:Post_answer)
    WHERE pa.parent_id IS NOT NULL
      AND pa.parent_id <> 0
    RETURN
        pa.post_id AS answer_id,
        pa.parent_id AS question_id
    ",
    "
    MATCH (pa:Post_answer {post_id: answer_id})
    MATCH (pq:Post_question {post_id: question_id})
    MERGE (pa)-[:ANSWERS_TO]->(pq)
    ",
    {
        batchSize: 20000,
        parallel: false,
        retries: 2
    }
);