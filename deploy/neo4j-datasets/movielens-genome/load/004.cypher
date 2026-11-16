// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 4
CALL apoc.periodic.iterate(
    'CALL apoc.load.json("file:///movielens/genome_2021/raw/tags.json")',
    '
    MERGE (t:Tag {tag_id: toInteger(value.id)})
    SET t.tag = value.tag
    ',
    {batchSize: 1000, parallel: true}
)