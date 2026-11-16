// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 32
MATCH (a1:Actor)-[:ACTED_IN]->(m:Movie)<-[:ACTED_IN]-(a2:Actor),
      (a3:Actor)-[:ACTED_IN]->(m)<-[:ACTED_IN]-(a4:Actor)
WHERE a1.name < a2.name AND a2.name < a3.name AND a3.name < a4.name
RETURN m.title AS Movie, a1.name AS Actor1, a2.name AS Actor2, a3.name AS Actor3, a4.name AS Actor4