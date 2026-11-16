// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 13

// Q19. Interaction path between cities
// Requires the Neo4j Graph Data Science library
MATCH
  (person1:Person)-[:IS_LOCATED_IN]->(city1:City {id: $city1Id}),
  (person2:Person)-[:IS_LOCATED_IN]->(city2:City {id: $city2Id})
CALL gds.shortestPath.dijkstra.stream('bi19', {
  sourceNode: person1,
  targetNode: person2,
  relationshipWeightProperty: 'weight'
})
YIELD totalCost
WITH person1.id AS person1Id, person2.id AS person2Id, totalCost AS totalWeight
ORDER BY totalWeight ASC, person1.id ASC, person2.id ASC
WITH collect({person1Id: person1Id, person2Id: person2Id, totalWeight: totalWeight}) AS results
UNWIND results AS result
WITH result.person1Id AS person1Id, result.person2Id AS person2Id, result.totalWeight AS totalWeight
WHERE totalWeight = results[0].totalWeight
RETURN person1Id, person2Id, totalWeight
ORDER BY person1Id, person2Id

// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 14

CALL gds.graph.project.cypher(
    'bi19',
    'MATCH (p:Person) RETURN id(p) AS id',
    'MATCH
      (personA:Person)-[:KNOWS]-(personB:Person),
      (personA)<-[:HAS_CREATOR]-(:Message)-[replyOf:REPLY_OF]-(:Message)-[:HAS_CREATOR]->(personB)
    WITH
      id(personA) AS source,
      id(personB) AS target,
      count(replyOf) AS numInteractions
    RETURN
      source,
      target,
      CASE WHEN round(40-sqrt(numInteractions)) > 1 THEN round(40-sqrt(numInteractions)) ELSE 1 END AS weight'
)

// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 15
CALL gds.graph.drop('bi19', false)