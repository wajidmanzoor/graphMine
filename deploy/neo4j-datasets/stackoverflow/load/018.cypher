// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 23
CALL apoc.periodic.iterate(
    "
    MATCH (ptwe:Post_tag_wiki_excerpt)
    WHERE ptwe.last_editor_user_id IS NOT NULL
      AND ptwe.last_editor_user_id <> 0
    RETURN
        ptwe.post_id AS excerpt_post_id,
        ptwe.last_editor_user_id AS editor_user_id
    ",
    "
    MATCH (ptwe:Post_tag_wiki_excerpt {post_id: excerpt_post_id})
    MATCH (u:User {user_id: editor_user_id})
    MERGE (ptwe)-[:LAST_EDITED_BY]->(u)
    ",
    {
        batchSize: 10000,
        parallel: false,
        retries: 2
    }
);