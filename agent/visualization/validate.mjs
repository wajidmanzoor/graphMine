import {readFileSync} from "node:fs";
import {compile} from "vega-lite";
import {parse, View} from "vega";

const input = JSON.parse(readFileSync(0, "utf8"));
const warnings = [];
const logger = {level(){return this;}, debug(){}, info(){}, warn(...args){warnings.push(args.map(String).join(" "));}, error(...args){throw new Error(args.map(String).join(" "));}};
try {
  const compiled = compile(input, {logger}).spec;
  const runtime = parse(compiled);
  const view = new View(runtime, {renderer:"none", logger, loader:{load(){throw new Error("External chart data is disabled");}, sanitize(){throw new Error("External chart resources are disabled");}}});
  await view.runAsync();
  const svg = await view.toSVG();
  view.finalize();
  process.stdout.write(JSON.stringify({ok:true, warnings, svg_bytes:Buffer.byteLength(svg), svg:process.argv.includes("--svg") ? svg : undefined}));
} catch (error) {
  process.stdout.write(JSON.stringify({ok:false, error:String(error), warnings}));
  process.exitCode = 1;
}
