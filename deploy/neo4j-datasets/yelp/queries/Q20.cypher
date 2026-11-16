// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 46
MATCH p = (:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND*1..3]-(neighbor:User)
RETURN length(p) AS path_length,
       count(p) AS path_count,
       count(DISTINCT neighbor) AS distinct_neighbor_count
ORDER BY path_length ASC