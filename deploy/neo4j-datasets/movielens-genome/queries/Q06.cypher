// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 20
MATCH (m:Movie)-[ht:HAS_TAG]->(t:Tag)
WHERE ht.count >= 20
RETURN m.title AS Movie, t.tag AS Tag, ht.count AS TagCount
ORDER BY TagCount DESC