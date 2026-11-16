// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 29

// T4.3. Enrolment-year statistics over all study relationships
MATCH (:Person)-[studyAt:STUDY_AT]->(:University)
RETURN count(studyAt) AS edgeCount,
       avg(studyAt.classYear) AS avgClassYear,
       min(studyAt.classYear) AS minClassYear,
       max(studyAt.classYear) AS maxClassYear