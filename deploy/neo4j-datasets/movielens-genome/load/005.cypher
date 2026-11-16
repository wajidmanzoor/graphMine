// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 5
CALL apoc.periodic.iterate(
    'CALL apoc.load.json("file:///movielens/genome_2021/raw/tag_count.json")',
    '
    MATCH (m:Movie {item_id: toInteger(value.item_id)})
    MATCH (t:Tag {tag_id: toInteger(value.tag_id)})
    MERGE (m)-[r:HAS_TAG]->(t)
    SET r.count = toInteger(value.num)
    ',
    {batchSize: 1000,parallel: false}
)