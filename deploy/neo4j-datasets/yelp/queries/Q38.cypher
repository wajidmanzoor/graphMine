// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 84

MATCH (b:Business)
WHERE b.latitude IS NOT NULL AND b.longitude IS NOT NULL
SET b.location = point({latitude: b.latitude, longitude: b.longitude})

// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 85

CREATE POINT INDEX business_location_index FOR (b:Business) ON (b.location)

// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 86

WITH point({latitude: 39.877788, longitude: -75.69293535784999}) AS center
MATCH (b:Business)
WHERE b.location IS NOT NULL
RETURN b.name, b.address, b.city, b.state,
b.latitude, b.longitude,
point.distance(b.location, center) AS dist_meters
ORDER BY dist_meters ASC
LIMIT 10