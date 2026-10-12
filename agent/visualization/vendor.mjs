import {copyFileSync, readFileSync, writeFileSync} from "node:fs";
import {createHash} from "node:crypto";
import {fileURLToPath} from "node:url";

const destination = new URL("../graphmine_agent/static/vendor/", import.meta.url);
const sources = {
  "vega.min.js": "vega/build/vega.min.js",
  "vega-lite.min.js": "vega-lite/build/vega-lite.min.js",
  "vega-embed.min.js": "vega-embed/build/vega-embed.min.js",
  "vega-lite-schema.json": "vega-lite/build/vega-lite-schema.json",
  "vega.LICENSE": "vega/LICENSE",
  "vega-lite.LICENSE": "vega-lite/LICENSE",
  "vega-embed.LICENSE": "vega-embed/LICENSE"
};
const manifest = {packages: JSON.parse(readFileSync(new URL("package.json", import.meta.url))).dependencies, files:{}};
for (const [name, source] of Object.entries(sources)) {
  const input = new URL(`node_modules/${source}`, import.meta.url);
  const output = new URL(name, destination);
  copyFileSync(input, output);
  manifest.files[name] = {source, sha256: createHash("sha256").update(readFileSync(output)).digest("hex")};
}
writeFileSync(new URL("vega-manifest.json", destination), JSON.stringify(manifest, null, 2) + "\n");
process.stdout.write(`Vendored ${Object.keys(sources).length} pinned assets into ${fileURLToPath(destination)}\n`);
