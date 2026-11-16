// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 75
MATCH (a:Actor)-[:ACTED_IN]->(m:Movie)<-[:DIRECTED]-(d:Director)
WHERE m.avgRating >= 4.0
WITH a.name AS Actor, count(DISTINCT d.name) AS UniqueTopDirectors, count(DISTINCT m) AS TopRatedMovies
WHERE TopRatedMovies >= 3
RETURN Actor, UniqueTopDirectors, TopRatedMovies
ORDER BY UniqueTopDirectors DESC, TopRatedMovies DESC