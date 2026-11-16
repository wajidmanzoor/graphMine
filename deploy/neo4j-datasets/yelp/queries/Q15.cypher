// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 36

MATCH (u:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND]->(friend:User)-[:WROTE]->(r:Review)-[:REVIEWS]->(b:Business)
RETURN DISTINCT friend.name AS friend_name,
b.name AS business_name,
b.address, b.city, b.state,
b.latitude, b.longitude
ORDER BY friend_name, business_name