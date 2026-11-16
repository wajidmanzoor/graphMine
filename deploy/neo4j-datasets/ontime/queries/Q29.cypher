// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 56

MATCH ()-[r1]->(n)-[r2]->()
WHERE (r1.FlightDate = date($date))
AND (r1.FlightDate = r2.FlightDate)
AND (r1.Tail_Number = r2.Tail_Number)
AND (r1.Tail_Number IS NOT NULL)
AND (r1.Tail_Number <> "")
AND (r1.CRSArrTime < r2.CRSDepTime)
WITH n, count(DISTINCT r1.Tail_Number) AS cnt
RETURN n, cnt
ORDER BY cnt DESC
LIMIT 10