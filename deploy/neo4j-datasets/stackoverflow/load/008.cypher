// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 12
CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///stackoverflow/tags.csv' AS row RETURN row",
    "
        MERGE (t:Tag {tag_id: toInteger(row.id)})
        SET t.tag_name        = row.tag_name,
        t.count           = toInteger(row.count),
        t.excerpt_post_id = toInteger(row.excerpt_post_id),
        t.wiki_post_id    = toInteger(row.wiki_post_id)
    ",
    {batchSize: 2000, parallel: true, concurrency: 2}
);