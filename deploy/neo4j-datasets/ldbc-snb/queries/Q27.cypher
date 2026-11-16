// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 33

CALL gds.graph.project(
  'KnowsGraph',
  'Person',
  {
    KNOWS: {
      type: 'KNOWS',
      orientation: 'UNDIRECTED'
    }
  }
)
YIELD graphName, nodeCount, relationshipCount, projectMillis
RETURN graphName, nodeCount, relationshipCount, projectMillis;

// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 34

CALL gds.degree.stream('KnowsGraph')
YIELD nodeId, score
WITH gds.util.asNode(nodeId) AS person, score
RETURN person.id AS personId,
       person.firstName AS firstName,
       person.lastName AS lastName,
       toInteger(score) AS degree
ORDER BY degree DESC
LIMIT 10;