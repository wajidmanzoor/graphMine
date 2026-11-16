// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 71
MATCH (v:Vote)-[:VOTE_ON]->(target)
UNWIND labels(target) AS targetLabel
RETURN v.vote_type_id AS voteTypeId,
       targetLabel,
       count(v) AS voteCount,
       min(v.creation_date) AS firstVoteDate,
       max(v.creation_date) AS lastVoteDate
ORDER BY voteCount DESC;