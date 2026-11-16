// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 75

MATCH (u:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND]->(:User)-[:WROTE]->(:Review)-[:REVIEWS]->(b:Business)
WHERE b.latitude IS NOT NULL AND b.longitude IS NOT NULL
WITH DISTINCT b.id AS bid, b.latitude AS lat, b.longitude AS lon
RETURN
percentileCont(lat, 0.5) AS median_latitude,
percentileCont(lon, 0.5) AS median_longitude