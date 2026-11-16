// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 47
MATCH p = (:Post_question {post_id: 840765})-[:LINK_TO*1..4]->(:Post_question {post_id: 1361149})
RETURN count(p) > 0 AS reachable
LIMIT 1;