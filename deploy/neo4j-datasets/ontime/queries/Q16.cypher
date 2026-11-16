// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 33
MATCH p = (a:Airport)-[:FLIGHT]->(b:Airport)-[:FLIGHT]->(c:Airport)-[:FLIGHT]->(d:Airport)
WHERE a <> b AND a <> c AND a <> d AND b <> c AND b <> d AND c <> d
RETURN a.code AS airport_a, b.code AS airport_b, c.code AS airport_c, d.code AS airport_d, p
LIMIT $limit;