// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 65
MATCH (m:Movie)-[ht:HAS_TAG]->(t:Tag)
MATCH (s:Survey)-[:ABOUT_MOVIE]->(m)
MATCH (s)-[:ABOUT_TAG]->(t)
WITH m.title AS Movie, t.tag AS Tag,
    sum(ht.count) AS TagApplications,
    avg(s.score) AS AvgSurveyScore,
    count(s) AS SurveyMentions
WHERE TagApplications > 5 AND SurveyMentions >= 5
RETURN Movie, Tag, TagApplications, round(AvgSurveyScore, 2) AS AvgSurveyScore, SurveyMentions
ORDER BY AvgSurveyScore DESC, SurveyMentions DESC