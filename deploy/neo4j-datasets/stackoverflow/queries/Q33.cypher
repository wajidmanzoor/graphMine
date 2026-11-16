// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 99
MATCH (u:User)-[:EARNED]->(b:Badge)
WHERE b.class = 1
AND u.creation_date IS NOT NULL
AND b.date IS NOT NULL
AND u.creation_date <> ''
AND b.date <> ''
WITH b.name AS badge_name,
     COUNT(DISTINCT u.user_id) AS total_earners,
     MIN(
        (toInteger(substring(b.date, 0, 4)) - toInteger(substring(u.creation_date, 0, 4))) * 365 +
        (toInteger(substring(b.date, 5, 2)) - toInteger(substring(u.creation_date, 5, 2))) * 30  +
        (toInteger(substring(b.date, 8, 2)) - toInteger(substring(u.creation_date, 8, 2)))
     ) AS min_days
WHERE min_days >= 0
RETURN badge_name, total_earners, min_days
ORDER BY total_earners DESC
LIMIT 100;