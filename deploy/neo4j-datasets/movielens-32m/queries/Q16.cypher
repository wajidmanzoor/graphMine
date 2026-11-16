// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 35
MATCH (u:User)-[r:RATED]->(m:Movie)-[:HAS_GENRE]->(g:Genre {name: "Comedy"})
RETURN u.userId AS userId, m.title AS movieTitle, g.name AS genre, r.rating AS rating
ORDER BY r.rating DESC
LIMIT 20;