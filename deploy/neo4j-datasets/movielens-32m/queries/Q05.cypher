// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 13
MATCH (m:Movie)
WHERE m.title CONTAINS "Love"
  AND m.movieId >= 99
RETURN m.movieId AS movieId, m.title AS title
ORDER BY m.movieId;