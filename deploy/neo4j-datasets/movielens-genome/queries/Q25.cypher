// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 58
MATCH (s:Survey)-[:ABOUT_MOVIE]->(m:Movie)
RETURN m.title AS Movie, count(*) AS SurveyMentions
ORDER BY SurveyMentions DESC