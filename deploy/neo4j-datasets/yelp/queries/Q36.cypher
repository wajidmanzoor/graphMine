// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 79

MATCH (u:User)
RETURN u.name AS name, count(*) AS occurrences
ORDER BY occurrences DESC
LIMIT 30