// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 87

MATCH (r:Review)
WHERE toLower(r.text) CONTAINS "disgusting"
RETURN r.id, r.text
LIMIT 100