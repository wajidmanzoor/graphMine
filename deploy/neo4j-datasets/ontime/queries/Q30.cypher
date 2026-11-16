// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 58

MATCH ()-[r1]->()-[r2]->()-[r3]->()
WHERE (r1.FlightDate = date($date))
AND (r1.FlightDate = r2.FlightDate)
AND (r1.FlightDate = r3.FlightDate)
AND (r1.Tail_Number = r2.Tail_Number)
AND (r1.Tail_Number = r3.Tail_Number)
AND (r1.Tail_Number IS NOT NULL)
AND (r1.Tail_Number <> "")
AND (r1.CRSArrTime < r2.CRSDepTime)
AND (r2.CRSArrTime < r3.CRSDepTime)
RETURN count(DISTINCT r1.Tail_Number) AS cnt