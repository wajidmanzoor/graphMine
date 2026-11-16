// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 30
MATCH (m:Movie)
OPTIONAL MATCH (a:Actor)-[:ACTED_IN]->(m)
OPTIONAL MATCH (m)-[:HAS_TAG]->(t:Tag)
OPTIONAL MATCH (m)-[:HAS_REVIEW]->(r:Review)
WITH m, count(DISTINCT a) AS ActorCount, count(DISTINCT t) AS TagCount, count(DISTINCT r) AS ReviewCount
WHERE ActorCount >= 2 AND TagCount >= 2
RETURN m.title AS Movie, ActorCount, TagCount, ReviewCount, ActorCount + TagCount + ReviewCount AS StarDegree
ORDER BY StarDegree DESC