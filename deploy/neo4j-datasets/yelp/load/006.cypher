// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 6

CALL apoc.periodic.iterate(
  "MATCH (b:Business) WHERE b.categories IS NOT NULL RETURN b",
  "
  WITH b, apoc.text.split(b.categories, ',') AS categoryList
  UNWIND categoryList AS rawCategory
  WITH b, trim(rawCategory) AS category
  MERGE (c:Category {name: category})
  CREATE (b)-[:IN_CATEGORY]->(c)
  ",
  {batchSize: 1000, parallel: false})