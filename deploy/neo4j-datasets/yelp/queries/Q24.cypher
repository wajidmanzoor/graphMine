// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 54

MATCH (b:Business {name: "Acme Oyster House"})
MATCH (b)<-[:REVIEWS]-(r:Review)
RETURN b.id AS business_id, r.text AS text, 'review' AS type

UNION

MATCH (b:Business {name: "Acme Oyster House"})
MATCH (b)<-[:FOR]-(t:Tip)<-[:TIPPED]-(:User)
RETURN b.id AS business_id, t.text AS text, 'tip' AS type