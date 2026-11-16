// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 53
MATCH p = (src:Post_question {post_id: 840765})-[:LINK_TO*1..3]->(dst:Post_question {post_id: 1361149})
WHERE all(n IN nodes(p) WHERE single(m IN nodes(p) WHERE m = n))
WITH p, reduce(pathScore = 0, n IN nodes(p) | pathScore + coalesce(n.score, 0)) AS totalScore
RETURN [n IN nodes(p) | n.post_id] AS questionPath, length(p) AS hopCount, totalScore
ORDER BY totalScore DESC, hopCount ASC
LIMIT 100;