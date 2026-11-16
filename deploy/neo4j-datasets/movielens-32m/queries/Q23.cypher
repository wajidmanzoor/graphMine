// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 49
MATCH p = (:User {userId: 33})-[:RATED*1..3]-(m:Movie)-[:HAS_GENRE]->(g:Genre)
RETURN length(p) - 1 AS pathLength,
       g.name AS genre,
       count(p) AS pathCount,
       count(DISTINCT m) AS distinctMovieCount
ORDER BY pathLength, pathCount DESC;