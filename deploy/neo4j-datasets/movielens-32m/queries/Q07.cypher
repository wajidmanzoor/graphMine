// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 17
RETURN EXISTS {
  MATCH (:User {userId: 33})-[:RATED*1..3]-(:Movie {movieId: 66})
} AS reachable;