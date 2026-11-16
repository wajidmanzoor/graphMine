// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 24
CALL apoc.periodic.iterate(
    "
    MATCH (b:Badge)
    WHERE b.user_id IS NOT NULL
      AND b.user_id <> 0
    RETURN
        b.badge_id AS badge_id,
        b.user_id AS user_id
    ",
    "
    MATCH (b:Badge {badge_id: badge_id})
    MATCH (u:User {user_id: user_id})
    MERGE (u)-[:EARNED]->(b)
    ",
    {
        batchSize: 20000,
        parallel: false,
        retries: 2
    }
);