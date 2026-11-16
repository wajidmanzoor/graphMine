// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 60
MATCH (u:User)-[:ANSWERED]->(s:Survey)
RETURN u.user_id AS User, count(s) AS TotalSurveys
ORDER BY TotalSurveys DESC