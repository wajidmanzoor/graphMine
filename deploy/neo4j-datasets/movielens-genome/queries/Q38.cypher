// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 78
MATCH (m:Movie)-[:HAS_REVIEW]->(r:Review)
WHERE toLower(r.text) CONTAINS 'boring'
OR toLower(r.text) CONTAINS 'disgusting'
OR toLower(r.text) CONTAINS 'waste'
OR toLower(r.text) CONTAINS 'terrible'
OR toLower(r.text) CONTAINS 'bad'
WITH m.title AS Movie, count(*) AS NegativeMentions
RETURN Movie, NegativeMentions
ORDER BY NegativeMentions DESC