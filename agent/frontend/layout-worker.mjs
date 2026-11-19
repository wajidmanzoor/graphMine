import cytoscape from 'cytoscape';
import fcose from 'cytoscape-fcose';
import ELK from 'elkjs/lib/elk.bundled.js';
cytoscape.use(fcose);
self.onmessage = async ({data}) => {
  let cy;
  try {
    if (data.nodes.length > 50000 || data.edges.length > 100000) throw new Error('Layout exceeds the display budget.');
    if (data.layout === 'hierarchical') {
      const graph = await new ELK().layout({id: 'scene', layoutOptions: {'elk.algorithm': 'layered', 'elk.direction': 'RIGHT', 'elk.randomSeed': String(data.seed || 0)}, children: data.nodes.map(n => ({id: n.id, width: 100, height: 64})), edges: data.edges.map((e, i) => ({id: 'e' + i, sources: [e.source], targets: [e.target]}))});
      self.postMessage({positions: graph.children.map(n => ({id: n.id, x: n.x, y: n.y})), method: 'ELK layered / worker'});
      return;
    }
    // A spatial grid bounds repulsion for large scenes. Fixed iterations and
    // input order make the display refinement reproducible, with no RNG.
    if (data.nodes.length > 2000) {
      const nodes = data.nodes.map(n => ({...n, dx: 0, dy: 0})), lookup = new Map(nodes.map(n => [n.id, n]));
      for (let iteration = 0; iteration < 120; iteration++) {
        const cells = new Map();
        for (const n of nodes) { n.dx = n.dy = 0; const key = `${Math.floor(n.x / 100)},${Math.floor(n.y / 100)}`; if (!cells.has(key)) cells.set(key, []); cells.get(key).push(n); }
        for (const n of nodes) {
          const x = Math.floor(n.x / 100), y = Math.floor(n.y / 100);
          for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) for (const other of (cells.get(`${x + i},${y + j}`) || []).slice(0, 32)) {
            if (n === other) continue; const dx = n.x - other.x, dy = n.y - other.y, d = Math.max(1, dx * dx + dy * dy); n.dx += dx * 70 / d; n.dy += dy * 70 / d;
          }
        }
        for (const edge of data.edges) { const a = lookup.get(edge.source), b = lookup.get(edge.target); if (!a || !b || a === b) continue; const x = b.x - a.x, y = b.y - a.y, distance = Math.hypot(x, y) || 1, pull = Math.max(-5, Math.min(5, (distance - 110) * .015)) / distance; a.dx += x * pull; a.dy += y * pull; b.dx -= x * pull; b.dy -= y * pull; }
        for (const n of nodes) if (!n.pinned) { n.x += Math.max(-12, Math.min(12, n.dx)); n.y += Math.max(-12, Math.min(12, n.dy)); }
      }
      self.postMessage({positions: nodes.map(({id, x, y}) => ({id, x, y})), method: 'bounded spatial spring display layout / worker / 120 iterations'});
      return;
    }
    cy = cytoscape({headless: true, styleEnabled: true, elements: [...data.nodes.map(n => ({data: {id: n.id}, position: {x: n.x, y: n.y}})), ...data.edges.map((e, i) => ({data: {id: 'e:' + i, ...e}}))], style: [{selector: 'node', style: {width: 60, height: 60}}]});
    cy.layout({name: 'fcose', quality: 'proof', randomize: false, animate: false, fit: false, numIter: 500, idealEdgeLength: () => 110, fixedNodeConstraint: data.nodes.filter(n => n.pinned).map(n => ({nodeId: n.id, position: {x: n.x, y: n.y}}))}).run();
    self.postMessage({positions: cy.nodes().map(n => ({id: n.id(), ...n.position()})), method: 'fCoSE / worker / 500 iterations'});
  } catch (error) { self.postMessage({error: error.message}); }
  finally { cy?.destroy(); }
};
