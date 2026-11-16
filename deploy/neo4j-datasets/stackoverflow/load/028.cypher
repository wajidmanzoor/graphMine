// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 33
CALL apoc.periodic.iterate(
    "
    MATCH (t:Tag)
    WHERE t.excerpt_post_id IS NOT NULL
      AND t.excerpt_post_id <> 0
    RETURN
        t.tag_id AS tag_id,
        t.excerpt_post_id AS excerpt_post_id
    ",
    "
    MATCH (t:Tag {tag_id: tag_id})
    MATCH (ptwe:Post_tag_wiki_excerpt {
        post_id: excerpt_post_id
    })
    MERGE (t)-[:HAS_WIKI_EXCERPT]->(ptwe)
    ",
    {
        batchSize: 10000,
        parallel: false,
        retries: 2
    }
);