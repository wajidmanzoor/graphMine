// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 16

// Q20. Recruitment
// Requires the Neo4j Graph Data Science library
MATCH
  (company:Company {name: $company})<-[:WORK_AT]-(person1:Person),
  (person2:Person {id: $person2Id})
CALL gds.shortestPath.dijkstra.stream('bi20', {
  sourceNode: person1,
  targetNode: person2,
  relationshipWeightProperty: 'weight'
})
YIELD totalCost
WHERE person1.id <> $person2Id
WITH person1.id AS person1Id, totalCost AS totalWeight
ORDER BY totalWeight ASC
WITH collect({person1Id: person1Id, totalWeight: totalWeight}) AS results
UNWIND results AS result
WITH result.person1Id AS person1Id, result.totalWeight AS totalWeight
WHERE totalWeight = results[0].totalWeight
RETURN person1Id, totalWeight
ORDER BY person1Id ASC
LIMIT 20

// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 17

CALL gds.graph.project.cypher(
    'bi20',
    'MATCH (p:Person) RETURN id(p) AS id',
    'MATCH
      (personA:Person)-[:KNOWS]-(personB:Person),
      (personA)-[saA:STUDY_AT]->(u:University)<-[saB:STUDY_AT]-(personB)
    RETURN
      id(personA) AS source,
      id(personB) AS target,
      min(abs(saA.classYear - saB.classYear)) + 1 AS weight'
)

// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 18
CALL gds.graph.drop('bi20', false)