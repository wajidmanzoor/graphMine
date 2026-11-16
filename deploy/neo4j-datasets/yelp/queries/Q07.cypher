// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 20
MATCH (source:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"}),
      (target:User {user_id: "WwulXySQN8t2hwqH_yWurA"})
RETURN EXISTS {
  MATCH (source)-[:FRIEND*1..4]-(target)
} AS reachable