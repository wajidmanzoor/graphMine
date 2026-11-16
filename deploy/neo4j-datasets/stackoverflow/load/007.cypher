// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 11
CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///stackoverflow/posts_questions_clean.csv' AS row RETURN row",
    "
        MERGE (pq:Post_question {post_id: toInteger(row.id)})
        SET pq.title                    = row.title,
        pq.body                     = row.body,
        pq.accepted_answer_id       = toInteger(row.accepted_answer_id),
        pq.answer_count             = toInteger(row.answer_count),
        pq.comment_count            = toInteger(row.comment_count),
        pq.community_owned_date     = row.community_owned_date,
        pq.creation_date            = row.creation_date,
        pq.favorite_count           = toInteger(row.favorite_count),
        pq.last_activity_date       = row.last_activity_date,
        pq.last_edit_date           = row.last_edit_date,
        pq.last_editor_display_name = row.last_editor_display_name,
        pq.last_editor_user_id      = toInteger(row.last_editor_user_id),
        pq.owner_display_name       = row.owner_display_name,
        pq.owner_user_id            = toInteger(row.owner_user_id),
        pq.parent_id                = toInteger(row.parent_id),
        pq.post_type_id             = toInteger(row.post_type_id),
        pq.score                    = toInteger(row.score),
        pq.tags                     = row.tags,
        pq.view_count               = toInteger(row.view_count)
    ",
    {batchSize: 2000, parallel: true, concurrency: 2}
    );