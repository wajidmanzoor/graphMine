// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 19
CALL apoc.periodic.iterate(
    "
    MATCH (ptwe:Post_tag_wiki_excerpt)
    WHERE ptwe.owner_user_id IS NOT NULL
      AND ptwe.owner_user_id <> 0
    RETURN
        ptwe.post_id AS excerpt_post_id,
        ptwe.owner_user_id AS owner_user_id
    ",
    "
    MATCH (ptwe:Post_tag_wiki_excerpt {post_id: excerpt_post_id})
    MATCH (u:User {user_id: owner_user_id})
    MERGE (ptwe)-[:CREATED_BY]->(u)
    ",
    {
        batchSize: 10000,
        parallel: false,
        retries: 2
    }
);