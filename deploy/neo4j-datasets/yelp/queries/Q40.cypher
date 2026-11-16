// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 89

MATCH (r:Review)
WITH split(toLower(r.text), " ") AS words
UNWIND words AS word
WITH word, count(*) AS freq
WHERE size(word) > 3
RETURN word, freq
ORDER BY freq DESC
LIMIT 20