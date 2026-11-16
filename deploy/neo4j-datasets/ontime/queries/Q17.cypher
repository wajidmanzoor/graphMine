// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 35
MATCH (airport:Airport)
OPTIONAL MATCH (airport)-[:FLIGHT]->(dest:Airport)
WITH airport, count(DISTINCT dest) AS out_degree
RETURN count(airport) AS airport_count,
       avg(out_degree) AS avg_out_degree,
       min(out_degree) AS min_out_degree,
       max(out_degree) AS max_out_degree;