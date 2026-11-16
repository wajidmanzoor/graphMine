// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 60
MATCH (m:Movie)-[:HAS_GENRE]->(g:Genre)
MATCH (u:User)-[r:RATED]->(m)
WITH m, collect(DISTINCT g.name) AS genres, count(DISTINCT r) AS ratingCount
WHERE size(genres) >= 3 AND ratingCount >= 50
RETURN m.title AS movie, genres, ratingCount
ORDER BY ratingCount DESC
LIMIT 10;