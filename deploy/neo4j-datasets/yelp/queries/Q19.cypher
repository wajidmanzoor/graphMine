// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 44
MATCH (:User)-[:WROTE]->(r:Review)-[:REVIEWS]->(b:Business)
RETURN b.state AS state,
       count(r) AS review_edge_count,
       avg(r.stars) AS avg_review_stars,
       min(r.stars) AS min_review_stars,
       max(r.stars) AS max_review_stars
ORDER BY review_edge_count DESC
LIMIT 25