// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 57
MATCH (q1:Post_question)-[:LINK_TO]->(q2:Post_question)-[:LINK_TO]->(q3:Post_question)-[:LINK_TO]->(q4:Post_question)-[:LINK_TO]->(q1)
WHERE q1.post_id < q2.post_id AND q1.post_id < q3.post_id AND q1.post_id < q4.post_id
  AND q2 <> q4
RETURN q1.post_id AS question1, q2.post_id AS question2, q3.post_id AS question3, q4.post_id AS question4;