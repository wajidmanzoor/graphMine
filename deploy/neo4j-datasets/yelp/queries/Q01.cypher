// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 8

MATCH (:User {name: "John"})-[:FRIEND]->(friend)
RETURN friend.name, friend.user_id
LIMIT 20