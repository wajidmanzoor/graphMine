// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 1
CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE;
CREATE CONSTRAINT post_question_id_unique IF NOT EXISTS FOR (pq:Post_question) REQUIRE pq.post_id IS UNIQUE;
CREATE CONSTRAINT post_answer_id_unique IF NOT EXISTS FOR (pa:Post_answer) REQUIRE pa.post_id IS UNIQUE;
CREATE CONSTRAINT comment_id_unique IF NOT EXISTS FOR (c:Comment) REQUIRE c.comment_id IS UNIQUE;
CREATE CONSTRAINT tag_id_unique IF NOT EXISTS FOR (t:Tag) REQUIRE t.tag_id IS UNIQUE;
CREATE CONSTRAINT badge_id_unique IF NOT EXISTS FOR (b:Badge) REQUIRE b.badge_id IS UNIQUE;
CREATE CONSTRAINT vote_id_unique IF NOT EXISTS FOR (v:Vote) REQUIRE v.vote_id IS UNIQUE;
CREATE CONSTRAINT post_history_id_unique IF NOT EXISTS FOR (ph:Post_history) REQUIRE ph.post_history_id IS UNIQUE;
CREATE CONSTRAINT post_tag_wiki_id_unique IF NOT EXISTS FOR (ptw:Post_tag_wiki) REQUIRE ptw.post_id IS UNIQUE;
CREATE CONSTRAINT post_tag_wiki_excerpt_id_unique IF NOT EXISTS FOR (ptwe:Post_tag_wiki_excerpt) REQUIRE ptwe.post_id IS UNIQUE;