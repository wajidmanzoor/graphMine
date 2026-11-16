// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 31
MATCH (a:Movie)-[:HAS_GENRE]->(:Genre)<-[:HAS_GENRE]-(b:Movie)
MATCH (a)-[:HAS_GENRE]->(:Genre)<-[:HAS_GENRE]-(c:Movie)
MATCH (a)-[:HAS_GENRE]->(:Genre)<-[:HAS_GENRE]-(d:Movie)
MATCH (b)-[:HAS_GENRE]->(:Genre)<-[:HAS_GENRE]-(c)
MATCH (b)-[:HAS_GENRE]->(:Genre)<-[:HAS_GENRE]-(d)
MATCH (c)-[:HAS_GENRE]->(:Genre)<-[:HAS_GENRE]-(d)
WHERE a.movieId < b.movieId AND b.movieId < c.movieId AND c.movieId < d.movieId
RETURN DISTINCT a.title AS movieA, b.title AS movieB, c.title AS movieC, d.title AS movieD;