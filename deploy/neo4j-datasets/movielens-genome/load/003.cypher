// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 3
CALL apoc.periodic.iterate(
    '
    CALL apoc.load.json("file:///movielens/genome_2021/raw/ratings.json")
    YIELD value
    RETURN value
    ',
    '
    MERGE (u:User {user_id: toInteger(value.user_id)})
    WITH u, value
    MATCH (m:Movie {item_id: toInteger(value.item_id)})
    CREATE (u)-[:RATED {rating: toFloat(value.rating)}]->(m)
    ',
    {batchSize: 1000, parallel: false}
);