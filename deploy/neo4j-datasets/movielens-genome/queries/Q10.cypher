// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 28
MATCH (u1:User)-[:RATED]->(m1:Movie)<-[:RATED]-(u2:User)-[:RATED]->(m2:Movie)<-[:RATED]-(u1)
WHERE u1.user_id < u2.user_id AND m1.item_id < m2.item_id
RETURN u1.user_id AS User1, u2.user_id AS User2, m1.title AS Movie1, m2.title AS Movie2