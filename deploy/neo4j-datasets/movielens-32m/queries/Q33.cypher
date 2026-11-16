// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 64
MATCH (u:User)-[r:RATED]->(m:Movie)<-[t:TAGGED]-(u)
WHERE r.timestamp < t.timestamp
WITH u.userId AS userId, m.title AS movieTitle, r.rating AS rating, r.timestamp AS ratingTime,
COLLECT(DISTINCT t.tag) AS tags
RETURN userId, movieTitle, rating, tags
ORDER BY ratingTime DESC
LIMIT 10;