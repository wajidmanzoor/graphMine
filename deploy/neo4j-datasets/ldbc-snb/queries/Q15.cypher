// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 21

// T3.3. Forums with the most members among those created after a given date
MATCH (forum:Forum)-[:HAS_MEMBER]->(person:Person)
WHERE forum.creationDate > $date
WITH forum, count(DISTINCT person) AS memberCount
WHERE memberCount >= $minDegree
RETURN forum.id AS forumId, forum.title AS title, memberCount
ORDER BY memberCount DESC, forumId
LIMIT $limit