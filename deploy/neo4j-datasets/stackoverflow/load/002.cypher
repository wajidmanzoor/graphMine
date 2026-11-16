// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 3
CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///stackoverflow/users_clean.csv' AS row RETURN row",
    "
    MERGE (u:User {user_id: toInteger(row.id)})
    SET u.display_name      = row.display_name,
        u.about_me          = row.about_me,
        u.age               = toInteger(row.age),
        u.creation_date     = row.creation_date,
        u.last_access_date  = row.last_access_date,
        u.location          = row.location,
        u.reputation        = toInteger(row.reputation),
        u.up_votes          = toInteger(row.up_votes),
        u.down_votes        = toInteger(row.down_votes),
        u.views             = toInteger(row.views),
        u.profile_image_url = row.profile_image_url,
        u.website_url       = row.website_url
    ",
    {batchSize: 20000, parallel: false, retries: 2}
);