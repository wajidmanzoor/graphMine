// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 73
MATCH (s:Survey)-[:ABOUT_MOVIE]->(m:Movie), (s)-[:ABOUT_TAG]->(t:Tag)
WHERE s.score >= 4
RETURN m.title AS Movie, t.tag AS Tag, count(*) AS HighScoreCount
ORDER BY HighScoreCount DESC