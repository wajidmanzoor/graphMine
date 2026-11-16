// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 26
CALL apoc.periodic.iterate(
    "
    MATCH (pq:Post_question)
    WHERE pq.accepted_answer_id IS NOT NULL
      AND pq.accepted_answer_id <> 0
    RETURN
        pq.post_id AS question_id,
        pq.accepted_answer_id AS answer_id
    ",
    "
    MATCH (pq:Post_question {post_id: question_id})
    MATCH (pa:Post_answer {post_id: answer_id})
    MERGE (pq)-[:ACCEPTS]->(pa)
    ",
    {
        batchSize: 20000,
        parallel: false,
        retries: 2
    }
);