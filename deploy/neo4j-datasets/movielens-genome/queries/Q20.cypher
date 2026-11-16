// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 48
MATCH p = (:User {user_id: 997206})-[:RATED*1..3]-(target)
RETURN length(p) AS PathLength,
       count(p) AS PathCount,
       count(DISTINCT target) AS DistinctTargets
ORDER BY PathLength ASC