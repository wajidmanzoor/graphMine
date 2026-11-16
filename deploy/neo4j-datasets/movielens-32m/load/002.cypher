// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 2
CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///movielens/ml-32m/movies.csv' AS row RETURN row",
    "CREATE (m:Movie {movieId: toInteger(row.movieId)})
    SET m.title = row.title
    WITH m, row
    UNWIND split(row.genres, '|') AS genreName
    WITH m, genreName WHERE genreName IS NOT NULL AND trim(genreName) <> ''
    MERGE (g:Genre {name: genreName})
    MERGE (m)-[:HAS_GENRE]->(g)",
    {batchSize: 10000, parallel: false}
)