// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 29
MATCH (u:User)-[:RATED]->(m:Movie)
WITH u, count(DISTINCT m) AS ratedMovieCount
WHERE ratedMovieCount >= 10
RETURN u.userId AS userId, ratedMovieCount
ORDER BY ratedMovieCount DESC;