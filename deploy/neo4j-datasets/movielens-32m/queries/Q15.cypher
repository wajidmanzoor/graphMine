// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 33
MATCH (u1:User)-[:RATED]->(m:Movie)<-[:RATED]-(u2:User)
WHERE u1.userId < u2.userId
RETURN u1.userId AS userA, u2.userId AS userB, m.title AS sharedMovie;