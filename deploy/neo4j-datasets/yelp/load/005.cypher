// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 5
CALL apoc.periodic.iterate(
  "CALL apoc.load.json('file:///yelp/yelp_academic_dataset_tip.json') YIELD value",
  "
  MATCH (u:User {user_id: value.user_id})
  MATCH (b:Business {id: value.business_id})
  CREATE (t:Tip {
    text: value.text,
    date: value.date,
    compliment_count: value.compliment_count
  })
  CREATE (u)-[:TIPPED]->(t)
  CREATE (t)-[:FOR]->(b)
  ",
  {batchSize: 1000, parallel: false}
)