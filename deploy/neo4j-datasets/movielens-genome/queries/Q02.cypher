// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 12
MATCH p = (u:User {user_id: 997206})-[:RATED*1..2]-(n)
WHERE n <> u
RETURN DISTINCT labels(n) AS NodeLabels,
       coalesce(n.title, toString(n.user_id)) AS Neighbor,
       length(p) AS HopCount
ORDER BY HopCount ASC, Neighbor