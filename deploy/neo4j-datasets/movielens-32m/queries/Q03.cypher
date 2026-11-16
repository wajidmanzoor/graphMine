// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 9
MATCH (:User {userId: 33})-[:RATED]->(:Movie)<-[:RATED]-(other:User)
WHERE other.userId <> 33
RETURN DISTINCT other.userId AS userId
ORDER BY userId;