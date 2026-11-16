// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 76

MATCH (b:Business)
WHERE b.latitude IS NOT NULL AND b.longitude IS NOT NULL
SET b.location = point({latitude: b.latitude, longitude: b.longitude})

// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 77

CREATE POINT INDEX business_location_index FOR (b:Business) ON (b.location)

// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 78

WITH point({latitude: 39.877788, longitude: -75.69293535784999}) AS center
MATCH (b:Business)
WHERE b.location IS NOT NULL AND point.distance(b.location, center) <= 8046.72
MATCH (u:User)-[:WROTE]->(:Review)-[:REVIEWS]->(b)
RETURN count(DISTINCT u) AS user_count