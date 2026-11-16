// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 40

MATCH (b:Business)<-[:REVIEWS]-(r:Review)
WITH b, collect(r.stars) AS stars
WHERE ALL(star IN stars WHERE star < 3)
RETURN b.name, stars
ORDER BY size(stars) DESC