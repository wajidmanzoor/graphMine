// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 54

MATCH p = (a)-[r1]->(b)-[r2]->(c)
WHERE (r1.FlightDate = r2.FlightDate)
AND (r1.CRSArrTime + 100 <= r2.CRSDepTime)
AND (r1.ArrTime >= r2.DepTime)
AND (a.airport_id = 12892)
AND (c.airport_id = 12953)
AND (r1.Year = $year) 
WITH r1.Month as month, count(p) as path_count
RETURN month, path_count
ORDER BY month