// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 7
CALL apoc.periodic.iterate(
    'CALL apoc.load.json("file:///movielens/genome_2021/raw/surveys_id.json") YIELD value',
    '
    MERGE (u:User {user_id: toInteger(value.user_id)})
    WITH u, value

    MATCH (m:Movie {item_id: toInteger(value.item_id)})
    MATCH (t:Tag {tag_id: toInteger(value.tag_id)})

    CREATE (s:Survey {
    survey_id: toInteger(value.survey_id),
    score: toInteger(value.score)
    })

    MERGE (u)-[:ANSWERED]->(s)
    MERGE (s)-[:ABOUT_MOVIE]->(m)
    MERGE (s)-[:ABOUT_TAG]->(t)
    ',
    {batchSize: 1000, parallel: false}
)