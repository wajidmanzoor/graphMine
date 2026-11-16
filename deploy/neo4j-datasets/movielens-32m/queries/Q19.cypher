// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 41
MATCH (:User)-[r:RATED]->(m:Movie)
WHERE r.rating = 5.0
RETURN m.title AS movieTitle, COUNT(*) AS fiveStarCount
ORDER BY fiveStarCount DESC
LIMIT 20;