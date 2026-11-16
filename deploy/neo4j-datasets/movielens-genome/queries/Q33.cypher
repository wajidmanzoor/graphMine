// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 69
MATCH (d:Director)-[:DIRECTED]->(m:Movie)-[:HAS_REVIEW]->(r:Review)
RETURN d.name AS Director, count(r) AS TotalReviews
ORDER BY TotalReviews DESC