// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 70

MATCH (:User {user_id: 'Oi1qbcz2m2SnwUeztGYcnQ'})
      -[:FRIEND]->(friend:User)
      -[:WROTE]->(:Review)
      -[:REVIEWS]->(business:Business)
WITH DISTINCT
     friend.user_id AS friend_id,
     business.id AS business_id
RETURN count(*) AS total_results