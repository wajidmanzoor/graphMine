// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 4
CALL apoc.periodic.iterate(
  "CALL apoc.load.json('file:///yelp/yelp_academic_dataset_review.json') YIELD value",
  "
  MATCH (u:User {user_id: value.user_id})
  MATCH (b:Business {id: value.business_id})
  CREATE (r:Review {
    id: value.review_id,
    stars: value.stars,
    date: value.date,
    text: value.text,
    useful: value.useful,
    funny: value.funny,
    cool: value.cool
  })
  CREATE (u)-[:WROTE]->(r)
  CREATE (r)-[:REVIEWS]->(b)
  ",
  {batchSize: 1000, parallel: false}
)