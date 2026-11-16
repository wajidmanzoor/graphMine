// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 1
// Unique Movie IDs
CREATE CONSTRAINT movie_id_unique IF NOT EXISTS
FOR (m:Movie) REQUIRE m.item_id IS UNIQUE;
// Unique User IDs
CREATE CONSTRAINT user_id_unique IF NOT EXISTS
FOR (u:User) REQUIRE u.user_id IS UNIQUE;
// Unique Tag IDs
CREATE CONSTRAINT tag_id_unique IF NOT EXISTS
FOR (t:Tag) REQUIRE t.tag_id IS UNIQUE;
// Unique Review IDs
CREATE CONSTRAINT review_id_unique IF NOT EXISTS
FOR (r:Review) REQUIRE r.review_id IS UNIQUE;
// Unique Survey IDs
CREATE CONSTRAINT survey_id_unique IF NOT EXISTS
FOR (s:Survey) REQUIRE s.survey_id IS UNIQUE;
// Unique Director Names
CREATE CONSTRAINT director_name_unique IF NOT EXISTS
FOR (d:Director) REQUIRE d.name IS UNIQUE;
// Unique Actor Names
CREATE CONSTRAINT actor_name_unique IF NOT EXISTS
FOR (a:Actor) REQUIRE a.name IS UNIQUE;