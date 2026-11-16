// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 36
MATCH (u:User)-[:ANSWERED]->(s:Survey)-[:ABOUT_MOVIE]->(m:Movie)-[:HAS_TAG]->(t:Tag)
RETURN u.user_id AS UserID, s.survey_id AS SurveyID, m.title AS Movie, t.tag AS Tag, s.score AS SurveyScore