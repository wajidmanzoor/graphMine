// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 31
CALL apoc.periodic.iterate(
    "
    LOAD CSV WITH HEADERS
    FROM 'file:///stackoverflow/edge_tag_to_question.csv' AS row

    WITH
        toIntegerOrNull(row.src) AS tag_id,
        toIntegerOrNull(row.dst) AS question_id

    WHERE tag_id IS NOT NULL
      AND question_id IS NOT NULL

    RETURN tag_id, question_id
    ",
    "
    MATCH (t:Tag {tag_id: tag_id})
    MATCH (pq:Post_question {post_id: question_id})
    MERGE (t)-[:TAG_TO]->(pq)
    ",
    {
        batchSize: 20000,
        parallel: false,
        retries: 2
    }
);