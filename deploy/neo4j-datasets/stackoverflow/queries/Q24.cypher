// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 81
CALL gds.graph.project(
  'StackOverflowQuestionLinksWcc',
  'Post_question',
  {LINK_TO: {type: 'LINK_TO', orientation: 'UNDIRECTED'}}
);

// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 82
CALL gds.wcc.stream('StackOverflowQuestionLinksWcc')
YIELD nodeId, componentId
RETURN componentId, count(*) AS componentSize
ORDER BY componentSize DESC;