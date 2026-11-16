// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 24
MATCH (u:User {user_id: 997206})
MATCH (t:Tag {tag_id: 22})
WITH u, t
LIMIT 1
MATCH p = shortestPath((u)-[:RATED|HAS_TAG*1..4]-(t))
RETURN [n IN nodes(p) | coalesce(n.title, n.tag, toString(n.user_id))] AS Path, length(p) AS Hops