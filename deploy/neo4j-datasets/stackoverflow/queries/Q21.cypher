// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 75
MATCH p = (:Post_question {post_id: 415631})-[:LINK_TO*1..3]->(target:Post_question)
WITH length(p) AS pathLength,
     CASE
       WHEN coalesce(target.answer_count, 0) = 0 THEN 'unanswered'
       WHEN coalesce(target.answer_count, 0) = 1 THEN 'single-answer'
       ELSE 'multi-answer'
     END AS answerBucket,
     p,
     target
RETURN pathLength, answerBucket, count(p) AS pathCount, count(DISTINCT target) AS endpointCount
ORDER BY pathLength, pathCount DESC;