// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 17
CALL apoc.periodic.iterate(
    "
    MATCH (pa:Post_answer)
    WHERE pa.owner_user_id IS NOT NULL
      AND pa.owner_user_id <> 0
    RETURN
        pa.post_id AS answer_id,
        pa.owner_user_id AS owner_user_id
    ",
    "
    MATCH (pa:Post_answer {post_id: answer_id})
    MATCH (u:User {user_id: owner_user_id})
    MERGE (pa)-[:ANSWERS_BY]->(u)
    ",
    {
        batchSize: 20000,
        parallel: false,
        retries: 2
    }
);