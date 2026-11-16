// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 22
CALL apoc.periodic.iterate(
    "
    MATCH (ptw:Post_tag_wiki)
    WHERE ptw.last_editor_user_id IS NOT NULL
      AND ptw.last_editor_user_id <> 0
    RETURN
        ptw.post_id AS wiki_post_id,
        ptw.last_editor_user_id AS editor_user_id
    ",
    "
    MATCH (ptw:Post_tag_wiki {post_id: wiki_post_id})
    MATCH (u:User {user_id: editor_user_id})
    MERGE (ptw)-[:LAST_EDITED_BY]->(u)
    ",
    {
        batchSize: 10000,
        parallel: false,
        retries: 2
    }
);