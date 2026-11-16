// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 30

// T4.4. Enrolment-year statistics grouped by university and gender
MATCH (person:Person)-[studyAt:STUDY_AT]->(university:University)
RETURN university.name AS universityName,
       person.gender AS gender,
       count(studyAt) AS edgeCount,
       avg(studyAt.classYear) AS avgClassYear,
       min(studyAt.classYear) AS minClassYear,
       max(studyAt.classYear) AS maxClassYear
ORDER BY edgeCount DESC, universityName, gender
LIMIT $limit