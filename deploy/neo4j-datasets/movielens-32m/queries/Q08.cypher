// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 19
MATCH (u:User {userId: 33})
MATCH (m:Movie {movieId: 66})
MATCH p = shortestPath((u)-[:RATED*1..4]-(m))
RETURN p, length(p) AS hopCount;