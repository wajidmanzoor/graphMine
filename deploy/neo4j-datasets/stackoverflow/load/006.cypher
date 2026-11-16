// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 9
CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///stackoverflow/posts_answers_clean.csv' AS row RETURN row",
    "
        MERGE (pa:Post_answer {post_id: toInteger(row.id)})
        SET pa.title                    = row.title,
        pa.body                     = row.body,
        pa.accepted_answer_id       = toInteger(row.accepted_answer_id),
        pa.answer_count             = toInteger(row.answer_count),
        pa.comment_count            = toInteger(row.comment_count),
        pa.community_owned_date     = row.community_owned_date,
        pa.creation_date            = row.creation_date,
        pa.favorite_count           = toInteger(row.favorite_count),
        pa.last_activity_date       = row.last_activity_date,
        pa.last_edit_date           = row.last_edit_date,
        pa.last_editor_display_name = row.last_editor_display_name,
        pa.last_editor_user_id      = toInteger(row.last_editor_user_id),
        pa.owner_display_name       = row.owner_display_name,
        pa.owner_user_id            = toInteger(row.owner_user_id),
        pa.parent_id                = toInteger(row.parent_id),
        pa.post_type_id             = toInteger(row.post_type_id),
        pa.score                    = toInteger(row.score),
        pa.tags                     = row.tags,
        pa.view_count               = toInteger(row.view_count)
    ",
    {batchSize: 2000, parallel: true, concurrency: 2}
);