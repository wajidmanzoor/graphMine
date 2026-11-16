// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 39
MATCH (u:User)-[:RATED]->(m:Movie)-[:HAS_GENRE]->(g:Genre)
WITH u, COUNT(DISTINCT g.name) AS genreCount
WHERE genreCount >= 3
RETURN u.userId AS userId, genreCount
ORDER BY genreCount DESC
LIMIT 10;