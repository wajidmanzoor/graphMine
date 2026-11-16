// Source: https://pgraphbenchweb.vercel.app/workloads/ml32m-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 1
// Unique User IDs
CREATE CONSTRAINT IF NOT EXISTS FOR (u:User) REQUIRE u.userId IS UNIQUE;
// Unique Movie IDs
CREATE CONSTRAINT IF NOT EXISTS FOR (m:Movie) REQUIRE m.movieId IS UNIQUE;
// Unique Genre Names
CREATE CONSTRAINT IF NOT EXISTS FOR (g:Genre) REQUIRE g.name IS UNIQUE;