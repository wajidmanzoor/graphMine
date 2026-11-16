// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 10
MATCH (u:User {user_id: 997206})-[r:RATED]->(m:Movie)
RETURN m.item_id AS MovieID, m.title AS Movie, r.rating AS Rating
ORDER BY Rating DESC