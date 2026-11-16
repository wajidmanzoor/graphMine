// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 46
MATCH (u:User)-[r:RATED]->(m:Movie)
WHERE r.rating IS NOT NULL
WITH u.user_id AS UserID, count(r) AS TotalRatings, round(avg(r.rating), 2) AS AvgRating
WHERE TotalRatings >= 5
RETURN UserID, AvgRating, TotalRatings
ORDER BY AvgRating ASC