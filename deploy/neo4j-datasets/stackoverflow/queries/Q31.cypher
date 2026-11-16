// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 95
MATCH (u:User)-[:EARNED]->(b:Badge)
WHERE u.creation_date IS NOT NULL
    AND b.date IS NOT NULL
    AND u.creation_date <> ''
    AND b.date <> ''
WITH u.user_id AS user_id,
     u.display_name  AS display_name,
     u.creation_date AS creation_date,
     MIN(
        (toInteger(substring(b.date, 0, 4)) - toInteger(substring(u.creation_date, 0, 4))) * 365 +
        (toInteger(substring(b.date, 5, 2)) - toInteger(substring(u.creation_date, 5, 2))) * 30  +
        (toInteger(substring(b.date, 8, 2)) - toInteger(substring(u.creation_date, 8, 2)))
     ) AS min_days
WHERE min_days >= 0
RETURN user_id, display_name, min_days
ORDER BY min_days ASC, user_id ASC
LIMIT 100;