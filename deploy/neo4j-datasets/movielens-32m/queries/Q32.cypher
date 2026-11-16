// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 62
MATCH (m:Movie)
OPTIONAL MATCH (m)-[:HAS_GENRE]->(g:Genre)
OPTIONAL MATCH (:User)-[t:TAGGED]->(m)
WITH m,
COLLECT(DISTINCT g.name) AS genres,
COLLECT(DISTINCT t.tag) AS tags,
SIZE(COLLECT(DISTINCT g.name)) + SIZE(COLLECT(DISTINCT t.tag)) AS total
ORDER BY total DESC
LIMIT 20
RETURN m.title AS movieTitle, total, genres, tags;