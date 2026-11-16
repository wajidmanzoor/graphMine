// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 80
MATCH (u:User)-[:ANSWERED]->(s:Survey)-[:ABOUT_TAG]->(t:Tag)
WITH u.user_id AS User, t.tag AS Tag, s.score AS UserScore
MATCH (s2:Survey)-[:ABOUT_TAG]->(t)
WHERE s2.score IS NOT NULL
WITH User, Tag, UserScore, avg(s2.score) AS Consensus
WITH User, avg(abs(UserScore - Consensus)) AS AvgDeviation, count(*) AS Count
WHERE Count >= 10
RETURN User, round(AvgDeviation, 2) AS AvgTagDisagreement, Count
ORDER BY AvgTagDisagreement ASC