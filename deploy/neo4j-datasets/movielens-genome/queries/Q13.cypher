// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 34
MATCH (u1:User)-[r1:RATED]->(m:Movie)<-[r2:RATED]-(u2:User)
WHERE u1 <> u2 AND abs(r1.rating - r2.rating) <= 1
WITH u1.user_id AS User1, u2.user_id AS User2, count(DISTINCT m) AS SharedMovies
WHERE SharedMovies >= 5
RETURN User1, User2, SharedMovies
ORDER BY SharedMovies DESC