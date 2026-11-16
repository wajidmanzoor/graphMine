// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 43
MATCH (:User)-[r:RATED]->(:Movie)
RETURN r.rating AS rating, COUNT(*) AS frequency
ORDER BY rating;