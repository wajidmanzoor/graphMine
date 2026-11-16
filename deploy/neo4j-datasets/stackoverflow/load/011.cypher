// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 16
CALL apoc.periodic.iterate(
    "
    MATCH (pq:Post_question)
    WHERE pq.owner_user_id IS NOT NULL
      AND pq.owner_user_id <> 0
    RETURN
        pq.post_id AS question_id,
        pq.owner_user_id AS owner_user_id
    ",
    "
    MATCH (pq:Post_question {post_id: question_id})
    MATCH (u:User {user_id: owner_user_id})
    MERGE (pq)-[:OWNED_BY]->(u)
    ",
    {
        batchSize: 20000,
        parallel: false,
        retries: 2
    }
);