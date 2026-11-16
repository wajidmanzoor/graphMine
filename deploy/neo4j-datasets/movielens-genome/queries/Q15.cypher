// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 38
MATCH (m:Movie)
OPTIONAL MATCH (m)-[]-(n)
WITH m, count(DISTINCT n) AS Degree
RETURN count(m) AS MovieCount,
       round(avg(Degree), 2) AS AvgDegree,
       min(Degree) AS MinDegree,
       max(Degree) AS MaxDegree