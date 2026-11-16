// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 34

MATCH (a:User {user_id: "Oi1qbcz2m2SnwUeztGYcnQ"})-[:FRIEND]->(mutual)<-[:FRIEND]-(b:User {user_id: "WwulXySQN8t2hwqH_yWurA"})
RETURN DISTINCT mutual.name, mutual.user_id