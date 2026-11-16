// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 48
MATCH p = (:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND*1..3]-(neighbor:User)
WITH p, neighbor,
     CASE
       WHEN neighbor.average_stars >= 4.0 THEN "high"
       WHEN neighbor.average_stars >= 3.0 THEN "medium"
       ELSE "low"
     END AS rating_bucket
RETURN length(p) AS path_length,
       rating_bucket,
       count(p) AS path_count,
       count(DISTINCT neighbor) AS distinct_neighbor_count
ORDER BY path_length ASC, path_count DESC
LIMIT 25