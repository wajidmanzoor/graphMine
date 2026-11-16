// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 49
MATCH p = shortestPath((src:Post_question {post_id: 840765})-[:LINK_TO*1..6]->(dst:Post_question {post_id: 1361149}))
RETURN [n IN nodes(p) | n.post_id] AS questionPath, length(p) AS hopCount;