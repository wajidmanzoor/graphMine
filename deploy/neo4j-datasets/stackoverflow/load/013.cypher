// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 18
CALL apoc.periodic.iterate(
    "
    MATCH (ptw:Post_tag_wiki)
    WHERE ptw.owner_user_id IS NOT NULL
      AND ptw.owner_user_id <> 0
    RETURN
        ptw.post_id AS wiki_post_id,
        ptw.owner_user_id AS owner_user_id
    ",
    "
    MATCH (ptw:Post_tag_wiki {post_id: wiki_post_id})
    MATCH (u:User {user_id: owner_user_id})
    MERGE (ptw)-[:CREATED_BY]->(u)
    ",
    {
        batchSize: 10000,
        parallel: false,
        retries: 2
    }
);