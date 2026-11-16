// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 73
MATCH p = (:Post_question {post_id: 415631})-[:LINK_TO*1..3]->(target:Post_question)
RETURN length(p) AS pathLength,
       count(p) AS pathCount,
       count(DISTINCT target) AS distinctTargetCount
ORDER BY pathLength;