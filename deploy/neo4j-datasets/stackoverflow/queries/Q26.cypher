// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 85
CALL gds.graph.project(
  'StackOverflowQuestionLinksLouvain',
  'Post_question',
  {LINK_TO: {type: 'LINK_TO', orientation: 'UNDIRECTED'}}
);

// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 86
CALL gds.louvain.stream('StackOverflowQuestionLinksLouvain')
YIELD nodeId, communityId
RETURN communityId, count(*) AS communitySize
ORDER BY communitySize DESC;