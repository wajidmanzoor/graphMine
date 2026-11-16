// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 30
CALL apoc.periodic.iterate(
    "
    MATCH (v:Vote)
    WHERE v.post_id IS NOT NULL
      AND v.post_id <> 0
    RETURN
        v.vote_id AS vote_id,
        v.post_id AS post_id
    ",
    "
    MATCH (v:Vote {vote_id: vote_id})

    OPTIONAL MATCH (pq:Post_question {post_id: post_id})
    OPTIONAL MATCH (pa:Post_answer {post_id: post_id})

    FOREACH (_ IN CASE WHEN pq IS NULL THEN [] ELSE [1] END |
        MERGE (v)-[:VOTE_ON]->(pq)
    )

    FOREACH (_ IN CASE WHEN pa IS NULL THEN [] ELSE [1] END |
        MERGE (v)-[:VOTE_ON]->(pa)
    )
    ",
    {
        batchSize: 20000,
        parallel: false,
        retries: 2
    }
);