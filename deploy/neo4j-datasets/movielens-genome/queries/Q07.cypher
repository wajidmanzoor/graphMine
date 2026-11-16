// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 22
MATCH (u:User {user_id: 997206})
MATCH (t:Tag {tag_id: 22})
WITH u, t
LIMIT 1
OPTIONAL MATCH p = (u)-[:RATED]->(:Movie)-[:HAS_TAG]->(t)
RETURN u.user_id AS UserID, t.tag AS Tag, count(p) > 0 AS Reachable