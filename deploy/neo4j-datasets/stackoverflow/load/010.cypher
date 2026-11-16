// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 15
CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///stackoverflow/posts_tag_wiki_excerpt.csv' AS row RETURN row",
    "
        MERGE (ptwe:Post_tag_wiki_excerpt {post_id: toInteger(row.id)})
        SET ptwe.title                    = row.title,
        ptwe.body                     = row.body,
        ptwe.comment_count            = toInteger(row.comment_count),
        ptwe.creation_date            = row.creation_date,
        ptwe.last_activity_date       = row.last_activity_date,
        ptwe.last_edit_date           = row.last_edit_date,
        ptwe.last_editor_display_name = row.last_editor_display_name,
        ptwe.last_editor_user_id      = toInteger(row.last_editor_user_id),
        ptwe.owner_display_name       = row.owner_display_name,
        ptwe.owner_user_id            = toInteger(row.owner_user_id),
        ptwe.post_type_id             = toInteger(row.post_type_id),
        ptwe.score                    = toInteger(row.score)
    ",
    {batchSize: 2000, parallel: true, concurrency: 2}
);