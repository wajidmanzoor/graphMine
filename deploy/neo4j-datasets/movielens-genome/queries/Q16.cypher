// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 40
MATCH (d:Director)-[:DIRECTED]->(m:Movie)
WHERE m.avgRating IS NOT NULL
WITH d.name AS Director, round(avg(m.avgRating), 2) AS AvgRating, count(m) AS Movies
WHERE Movies >= 3
RETURN Director, AvgRating, Movies
ORDER BY AvgRating DESC