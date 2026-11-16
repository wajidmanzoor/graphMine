// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 2
CALL apoc.periodic.iterate(
    'CALL apoc.load.json("file:///movielens/genome_2021/raw/metadata.json")',
    '
    MERGE (m:Movie {item_id: toInteger(value.item_id)})
    SET m.title = value.title,
        m.avgRating = toFloat(value.avgRating),
        m.imdbId = value.imdbId,
        m.directedBy = value.directedBy,
        m.starring = value.starring
    ',
    {batchSize: 1000, parallel: true}
)