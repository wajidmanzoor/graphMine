// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 26
MATCH (source:User {user_id: 997206})
MATCH (target:User)
WHERE target <> source
WITH source, target
LIMIT 1
MATCH p = (source)-[:RATED*1..3]-(target)
WHERE all(n IN nodes(p) WHERE single(x IN nodes(p) WHERE x = n))
RETURN [n IN nodes(p) | coalesce(n.title, toString(n.user_id))] AS Path, length(p) AS Hops