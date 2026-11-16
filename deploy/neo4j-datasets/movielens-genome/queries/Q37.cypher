// Source: https://pgraphbenchweb.vercel.app/workloads/mlgenome-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 77
MATCH (r:Review)
WHERE r.text IS NOT NULL
UNWIND apoc.text.split(toLower(r.text), "\W+") AS word
WITH word
WHERE size(word) > 3 AND NOT word IN [
    "this", "that", "with", "from", "have", "your",
    "just", "what", "when", "they", "were", "then",
    "there", "would", "which", "could", "really"
]
RETURN word, count(*) AS freq
ORDER BY freq DESC
LIMIT 20