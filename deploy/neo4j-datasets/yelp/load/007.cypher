// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 7

CALL apoc.periodic.iterate(
  "MATCH (u:User) WHERE u.friends IS NOT NULL RETURN u",
  "
  WITH u, apoc.text.split(u.friends, ', ') AS friendIds
  UNWIND friendIds AS friendId
  MATCH (f:User {user_id: friendId})
  CREATE(u)-[:FRIEND]->(f)
  ",
  {batchSize: 10000, parallel: false})