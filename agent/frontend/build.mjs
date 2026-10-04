// Reproducible offline browser assets; no CDN or external graph-data requests.
import {copyFileSync, mkdirSync} from 'node:fs';
const destination = new URL('../graphmine_agent/static/vendor/', import.meta.url);
mkdirSync(destination, {recursive: true});
copyFileSync(new URL('node_modules/cytoscape/dist/cytoscape.min.js', import.meta.url), new URL('cytoscape.min.js', destination));
copyFileSync(new URL('node_modules/cytoscape/LICENSE', import.meta.url), new URL('cytoscape.LICENSE', destination));
