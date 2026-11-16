// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 52
MATCH (d:Director)-[:DIRECTED]->(m:Movie)
WHERE m.avgRating >= 4.0
WITH d.name AS Director, count(m) AS HighRatedMovies
WHERE HighRatedMovies >= 2
RETURN Director, HighRatedMovies
ORDER BY HighRatedMovies DESC