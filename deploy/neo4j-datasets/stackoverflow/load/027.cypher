// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 32
CALL apoc.periodic.iterate(
    "
    MATCH (t:Tag)
    WHERE t.wiki_post_id IS NOT NULL
      AND t.wiki_post_id <> 0
    RETURN
        t.tag_id AS tag_id,
        t.wiki_post_id AS wiki_post_id
    ",
    "
    MATCH (t:Tag {tag_id: tag_id})
    MATCH (ptw:Post_tag_wiki {post_id: wiki_post_id})
    MERGE (t)-[:HAS_WIKI]->(ptw)
    ",
    {
        batchSize: 10000,
        parallel: false,
        retries: 2
    }
);