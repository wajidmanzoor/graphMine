// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 87
MATCH (u:User)
OPTIONAL MATCH (q:Post_question)-[:OWNED_BY]->(u)
OPTIONAL MATCH (vq:Vote)-[:VOTE_ON]->(q)
WITH u, COUNT(vq) AS q_votes
OPTIONAL MATCH (a:Post_answer)-[:ANSWERS_BY]->(u)
OPTIONAL MATCH (va:Vote)-[:VOTE_ON]->(a)
WITH u, q_votes, COUNT(va) AS a_votes
WITH u.user_id AS user_id,
     u.display_name AS display_name,
     q_votes + a_votes AS total_votes
WHERE total_votes > 0
RETURN user_id, display_name, total_votes
ORDER BY total_votes DESC;