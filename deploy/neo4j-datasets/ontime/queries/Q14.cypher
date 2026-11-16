// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 29
MATCH (a:Airport)-[:FLIGHT]-(b:Airport),
      (a)-[:FLIGHT]-(c:Airport),
      (a)-[:FLIGHT]-(d:Airport),
      (b)-[:FLIGHT]-(c),
      (b)-[:FLIGHT]-(d),
      (c)-[:FLIGHT]-(d)
WHERE a.airport_id < b.airport_id AND b.airport_id < c.airport_id AND c.airport_id < d.airport_id
RETURN a.code AS airport_a, b.code AS airport_b, c.code AS airport_c, d.code AS airport_d
LIMIT $limit;