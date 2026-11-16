// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 14
MATCH (u:User {user_id: 997206})-[:RATED]->(m:Movie)<-[:RATED]-(other:User)
WHERE other <> u
RETURN other.user_id AS SimilarUser, count(DISTINCT m) AS SharedMovies
ORDER BY SharedMovies DESC