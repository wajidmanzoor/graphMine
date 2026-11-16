// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 53
MATCH (u:User)-[:RATED]->(m1:Movie)-[:HAS_GENRE]->(g1:Genre {name: "Action"})
MATCH (u)-[:RATED]->(m2:Movie)-[:HAS_GENRE]->(g2:Genre {name: "Romance"})
RETURN DISTINCT u.userId AS userId
LIMIT 10;