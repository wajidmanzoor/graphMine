// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 16
MATCH (u:User {user_id: 997206})-[r:RATED]->(m:Movie)
WHERE r.rating >= 4.0 AND m.avgRating >= 4.0
RETURN m.item_id AS MovieID, m.title AS Movie, r.rating AS UserRating, m.avgRating AS AverageRating
ORDER BY UserRating DESC, AverageRating DESC