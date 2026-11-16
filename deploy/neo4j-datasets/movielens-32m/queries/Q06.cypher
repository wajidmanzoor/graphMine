// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 15
MATCH (u:User)-[r:RATED]->(m:Movie)
WHERE r.rating >= 4.0
RETURN u.userId AS userId, m.movieId AS movieId, m.title AS title, r.rating AS rating
ORDER BY rating DESC;