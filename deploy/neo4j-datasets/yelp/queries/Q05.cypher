// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 16
MATCH (b:Business)
WHERE b.state = "PA"
  AND b.is_open = 1
  AND b.rating >= 4.5
  AND b.review_count >= 100
RETURN b.name, b.city, b.rating, b.review_count
ORDER BY b.rating DESC, b.review_count DESC
LIMIT 25