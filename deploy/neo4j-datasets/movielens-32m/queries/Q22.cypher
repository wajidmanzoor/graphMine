// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 47
MATCH p = (:User {userId: 33})-[:RATED*1..3]-(target)
RETURN length(p) AS pathLength,
       count(p) AS pathCount,
       count(DISTINCT target) AS distinctTargetCount
ORDER BY pathLength;