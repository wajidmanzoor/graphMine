// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 44
MATCH (:User)-[r:RATED]->(:Movie)
RETURN count(r) AS RatingCount,
       round(avg(r.rating), 2) AS AvgRating,
       min(r.rating) AS MinRating,
       max(r.rating) AS MaxRating