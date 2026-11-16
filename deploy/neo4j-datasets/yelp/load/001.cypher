// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 1
// For Users
CREATE INDEX user_user_id_index FOR (u:User) ON (u.user_id);
// For Businesses
CREATE INDEX business_id_index FOR (b:Business) ON (b.id);