// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 6
CALL apoc.periodic.iterate(
    'CALL apoc.load.json("file:///movielens/genome_2021/raw/review_with_id.json")',
    '
    MATCH (m:Movie {item_id: toInteger(value.item_id)})
    CREATE (r:Review {
        review_id: toInteger(value.review_id),
        text: value.txt
    })
    MERGE (m)-[:HAS_REVIEW]->(r)
    ',
    {batchSize: 1000, parallel: false}
)