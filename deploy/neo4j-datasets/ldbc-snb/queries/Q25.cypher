// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 31

// T4.6. Friendship path counts by length and by the gender reached
MATCH p = (:Person {id: $personId})-[:KNOWS*1..3]-(neighbor:Person)
RETURN length(p) AS pathLength,
       neighbor.gender AS gender,
       count(p) AS pathCount,
       count(DISTINCT neighbor) AS distinctPersonCount
ORDER BY pathLength ASC, pathCount DESC
LIMIT $limit