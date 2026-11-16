// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 71
MATCH (d:Director)-[:DIRECTED]->(m:Movie)<-[:ACTED_IN]-(a:Actor)
WHERE m.avgRating IS NOT NULL
WITH d.name AS Director, a.name AS Actor, count(m) AS Collabs, round(avg(m.avgRating), 2) AS AvgRating
WHERE Collabs >= 3
RETURN Director, Actor, Collabs, AvgRating
ORDER BY AvgRating DESC