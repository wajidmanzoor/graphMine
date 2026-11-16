// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 54
MATCH (:Survey)-[:ABOUT_TAG]->(t:Tag)
RETURN t.tag AS Tag, count(*) AS SurveyCount
ORDER BY SurveyCount DESC