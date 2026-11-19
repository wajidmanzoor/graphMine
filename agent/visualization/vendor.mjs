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
  "vega-embed.LICENSE": "vega-embed/LICENSE",
  "vega-interpreter.LICENSE": "vega-interpreter/LICENSE"
};
const manifest = {packages: JSON.parse(readFileSync(new URL("package.json", import.meta.url))).dependencies, files:{}};
for (const [name, source] of Object.entries(sources)) {
  const input = new URL(`node_modules/${source}`, import.meta.url);
  const output = new URL(name, destination);
  copyFileSync(input, output);
  manifest.files[name] = {source, sha256: createHash("sha256").update(readFileSync(output)).digest("hex")};
}
// The pinned interpreter ships ESM. Reuse the exact helpers already exported by
// the vendored Vega runtime, avoiding a second vega-util bundle or runtime eval.
const interpreterSource = "vega-interpreter/build/vega-interpreter.js";
let interpreter = readFileSync(new URL(`node_modules/${interpreterSource}`, import.meta.url), "utf8");
const imports = "import { ascending, isString, DisallowedObjectProperties } from 'vega-util';";
const exports = "export { expression as expressionInterpreter };";
if (!interpreter.startsWith(imports) || !interpreter.includes(exports)) throw new Error("Interpreter module format changed; review the wrapper");
interpreter = "/* Vega interpreter 2.3.2; see vega-interpreter.LICENSE. */\n(() => {\n" + interpreter.replace(imports, "const {ascending, isString, DisallowedObjectProperties} = window.vega;").replace(exports, "window.vega.expressionInterpreter = expression;").replace(/\/\/# sourceMappingURL=.*\n?/, "") + "\n})();\n";
writeFileSync(new URL("vega-interpreter.js", destination), interpreter);
manifest.files["vega-interpreter.js"] = {source: interpreterSource, transform: "classic-script wrapper; helpers from pinned Vega", sha256: createHash("sha256").update(interpreter).digest("hex")};
writeFileSync(new URL("vega-manifest.json", destination), JSON.stringify(manifest, null, 2) + "\n");
process.stdout.write(`Vendored ${Object.keys(sources).length} pinned assets into ${fileURLToPath(destination)}\n`);
