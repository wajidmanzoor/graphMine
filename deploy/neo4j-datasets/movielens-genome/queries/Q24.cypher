// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 56
MATCH (s:Survey)-[:ABOUT_TAG]->(t:Tag)
WHERE s.score >= 4
RETURN t.tag AS Tag, count(*) AS HighScoreCount
ORDER BY HighScoreCount DESC