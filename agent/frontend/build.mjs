// Reproducible offline browser assets; no CDN or external graph-data requests.
import {copyFileSync, mkdirSync} from 'node:fs';
import {build} from 'esbuild';
copyFileSync(new URL('admin-neo4j.js', import.meta.url), new URL('../graphmine_agent/static/admin-neo4j.js', import.meta.url));
const destination = new URL('../graphmine_agent/static/vendor/', import.meta.url);
mkdirSync(destination, {recursive: true});
copyFileSync(new URL('node_modules/cytoscape/dist/cytoscape.min.js', import.meta.url), new URL('cytoscape.min.js', destination));
copyFileSync(new URL('node_modules/cytoscape/LICENSE', import.meta.url), new URL('cytoscape.LICENSE', destination));
await build({stdin: {contents: "import fcose from 'cytoscape-fcose'; import elk from 'cytoscape-elk'; window.cytoscape.use(fcose); window.cytoscape.use(elk); window.GraphMineLayoutsReady = true;", resolveDir: new URL('.', import.meta.url).pathname}, bundle: true, minify: true, format: 'iife', target: 'es2022', outfile: new URL('graph-layouts.min.js', destination).pathname, legalComments: 'eof'});
await build({entryPoints: [new URL('layout-worker.mjs', import.meta.url).pathname], bundle: true, minify: true, format: 'iife', target: 'es2022', outfile: new URL('layout-worker.min.js', destination).pathname, legalComments: 'eof'});
for (const [pkg, filename] of [['cytoscape-fcose', 'LICENSE'], ['cytoscape-elk', 'LICENSE'], ['elkjs', 'LICENSE.md'], ['cose-base', 'LICENSE'], ['layout-base', 'LICENSE']]) {
  copyFileSync(new URL(`node_modules/${pkg}/${filename}`, import.meta.url), new URL(`${pkg}.LICENSE`, destination));
}
for (const filename of ['leaflet.js', 'leaflet.css']) copyFileSync(new URL(`node_modules/leaflet/dist/${filename}`, import.meta.url), new URL(filename, destination));
copyFileSync(new URL('node_modules/leaflet/LICENSE', import.meta.url), new URL('leaflet.LICENSE', destination));
copyFileSync(new URL('node_modules/html2canvas/dist/html2canvas.min.js', import.meta.url), new URL('html2canvas.min.js', destination));
copyFileSync(new URL('node_modules/html2canvas/LICENSE', import.meta.url), new URL('html2canvas.LICENSE', destination));
for (const pkg of ['css-line-break', 'text-segmentation', 'utrie', 'base64-arraybuffer']) copyFileSync(new URL(`node_modules/${pkg}/LICENSE`, import.meta.url), new URL(`${pkg}.LICENSE`, destination));
mkdirSync(new URL('images/', destination), {recursive: true});
for (const filename of ['layers.png', 'layers-2x.png', 'marker-icon.png', 'marker-icon-2x.png', 'marker-shadow.png']) copyFileSync(new URL(`node_modules/leaflet/dist/images/${filename}`, import.meta.url), new URL(`images/${filename}`, destination));
