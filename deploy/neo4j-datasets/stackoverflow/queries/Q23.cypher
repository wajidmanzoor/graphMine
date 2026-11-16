// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 79
CALL gds.graph.project(
  'StackOverflowQuestionLinksPageRank',
  'Post_question',
  {LINK_TO: {type: 'LINK_TO', orientation: 'NATURAL'}}
);

// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 80
CALL gds.pageRank.stream('StackOverflowQuestionLinksPageRank')
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).post_id AS questionId,
       gds.util.asNode(nodeId).title AS title,
       score
ORDER BY score DESC;