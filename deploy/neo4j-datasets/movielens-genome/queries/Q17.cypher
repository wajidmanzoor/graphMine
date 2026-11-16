// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 42
MATCH (a:Actor)-[:ACTED_IN]->(m:Movie)
RETURN a.name AS Actor, count(m) AS TotalMovies
ORDER BY TotalMovies DESC