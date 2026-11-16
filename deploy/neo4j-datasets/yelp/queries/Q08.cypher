// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 22
MATCH p = shortestPath(
  (:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND*1..6]-(:User {user_id: "WwulXySQN8t2hwqH_yWurA"})
)
RETURN [n IN nodes(p) | n.name] AS user_path, length(p) AS hop_count