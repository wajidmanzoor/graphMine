// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 24
MATCH p = (:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND*1..3]-(:User {user_id: "WwulXySQN8t2hwqH_yWurA"})
WHERE all(i IN range(0, size(nodes(p)) - 1)
          WHERE single(n IN nodes(p) WHERE n = nodes(p)[i]))
RETURN [n IN nodes(p) | n.user_id] AS user_ids, length(p) AS hop_count
ORDER BY hop_count ASC
LIMIT 20