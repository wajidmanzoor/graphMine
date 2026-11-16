// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 21
MATCH p = (:User {userId: 33})-[:RATED*1..3]-(:Movie {movieId: 66})
WHERE all(n IN nodes(p) WHERE single(m IN nodes(p) WHERE m = n))
RETURN p, length(p) AS hopCount
ORDER BY hopCount;