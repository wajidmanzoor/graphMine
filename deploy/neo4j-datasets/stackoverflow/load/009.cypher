// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 14
CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///stackoverflow/posts_tag_wiki_clean.csv' AS row RETURN row",
    "
        MERGE (ptw:Post_tag_wiki {post_id: toInteger(row.id)})
        SET ptw.title                    = row.title,
        ptw.body                     = row.body,
        ptw.comment_count            = toInteger(row.comment_count),
        ptw.creation_date            = row.creation_date,
        ptw.last_activity_date       = row.last_activity_date,
        ptw.last_edit_date           = row.last_edit_date,
        ptw.last_editor_display_name = row.last_editor_display_name,
        ptw.last_editor_user_id      = toInteger(row.last_editor_user_id),
        ptw.owner_display_name       = row.owner_display_name,
        ptw.owner_user_id            = toInteger(row.owner_user_id),
        ptw.post_type_id             = toInteger(row.post_type_id),
        ptw.score                    = toInteger(row.score)
    ",
    {batchSize: 2000, parallel: true, concurrency: 2}
);