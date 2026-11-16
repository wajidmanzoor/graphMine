// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 34
CALL apoc.periodic.iterate(
    "
    LOAD CSV WITH HEADERS
    FROM 'file:///stackoverflow/posts_links.csv' AS row

    WITH
        toIntegerOrNull(row.id) AS post_link_id,
        toIntegerOrNull(row.post_id) AS source_post_id,
        toIntegerOrNull(row.related_post_id) AS target_post_id,
        toIntegerOrNull(row.link_type_id) AS link_type_id,
        row.creation_date AS creation_date

    WHERE post_link_id IS NOT NULL
      AND source_post_id IS NOT NULL
      AND target_post_id IS NOT NULL
      AND source_post_id <> 0
      AND target_post_id <> 0

    RETURN post_link_id, source_post_id, target_post_id,
           link_type_id, creation_date
    ",
    "
    MATCH (pq1:Post_question {post_id: source_post_id})
    MATCH (pq2:Post_question {post_id: target_post_id})

    MERGE (pq1)-[r:LINK_TO {post_link_id: post_link_id}]->(pq2)
    SET r.link_type_id = link_type_id,
        r.creation_date = creation_date
    ",
    {
        batchSize: 20000,
        parallel: false,
        retries: 2
    }
);