// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 83
CALL gds.graph.project(
  'StackOverflowQuestionLinksScc',
  'Post_question',
  {LINK_TO: {type: 'LINK_TO', orientation: 'NATURAL'}}
);

// Source: https://pgraphbenchweb.vercel.app/workloads/stackof-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 84
CALL gds.scc.stream('StackOverflowQuestionLinksScc')
YIELD nodeId, componentId
RETURN componentId, count(*) AS componentSize
ORDER BY componentSize DESC;