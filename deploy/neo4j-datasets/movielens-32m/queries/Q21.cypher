// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 45
MATCH (:User)-[t:TAGGED]->(:Movie)
WHERE t.tag IS NOT NULL
RETURN t.tag AS tag, COUNT(*) AS frequency
ORDER BY frequency DESC
LIMIT 50;