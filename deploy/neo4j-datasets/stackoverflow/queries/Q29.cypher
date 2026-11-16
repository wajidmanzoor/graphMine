// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 91
MATCH (a:Post_answer)-[:ANSWERS_TO]->(q:Post_question)
MATCH (a)-[:ANSWERS_BY]->(answerer:User)
MATCH (q)-[:OWNED_BY]->(questioner:User)
WHERE answerer.user_id <> questioner.user_id
WITH (answerer.user_id + ':' + questioner.user_id) AS pair_key,
    COUNT(*) AS interaction_count
WHERE interaction_count >= 5
RETURN pair_key, interaction_count
ORDER BY interaction_count DESC
LIMIT 100;