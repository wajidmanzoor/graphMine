// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 51
MATCH (m:Movie)-[:HAS_GENRE]->(g1:Genre {name: "Comedy"})
MATCH (m)-[:HAS_GENRE]->(g2:Genre {name: "Romance"})
RETURN m.title AS movieTitle
LIMIT 10;