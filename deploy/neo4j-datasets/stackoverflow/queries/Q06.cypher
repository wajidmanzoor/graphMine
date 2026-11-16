// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 45
MATCH (v:Vote)-[:VOTE_ON]->(p)
WHERE v.vote_type_id = 6
RETURN v.vote_id AS voteId, labels(p) AS postLabels,
       coalesce(p.post_id, p.comment_id) AS targetId,
       v.creation_date AS voteDate
ORDER BY voteDate DESC;