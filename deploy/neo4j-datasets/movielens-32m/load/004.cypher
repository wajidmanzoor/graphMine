// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 4
CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///movielens/ml-32m/tags.csv' AS row RETURN row",
    "
    MERGE (u:User {userId: toInteger(row.userId)})
    WITH u, row
    MATCH (m:Movie {movieId: toInteger(row.movieId)})
    CREATE (u)-[t:TAGGED]->(m)
    SET t.tag = row.tag,
    t.timestamp = apoc.date.format(toInteger(row.timestamp), 's', 'yyyy-MM-dd HH:mm:ss')
    ",
    {batchSize: 1000, parallel: false}
)