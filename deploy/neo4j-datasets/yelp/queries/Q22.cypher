// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 50

MATCH (b:Business)
OPTIONAL MATCH (b)<-[:REVIEWS]-(r:Review)
WITH b, count(DISTINCT r) AS num_reviews
OPTIONAL MATCH (b)<-[:FOR]-(t:Tip)<-[:TIPPED]-(:User)
WITH b, num_reviews, count(DISTINCT t) AS num_tips
RETURN b.name AS business_name,
       num_reviews,
       num_tips,
       num_reviews + num_tips AS total
ORDER BY total DESC