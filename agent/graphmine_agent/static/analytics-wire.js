/* Lossless JSON for integer IDs. No eval, generated code, or external runtime. */
(() => {
  "use strict";
  function parse(text) {
    let at = 0;
    const bad = () => { throw new SyntaxError(`Invalid JSON at character ${at}`); };
    const space = () => { while (/[ \t\r\n]/.test(text[at] || "") && at < text.length) at++; };
    function string() {
      const start = at++;
      while (at < text.length) {
        if (text[at] === '"') { at++; return JSON.parse(text.slice(start, at)); }
        if (text[at] === "\\") at++;
        at++;
      }
      return bad();
    }
    function value(depth = 0) {
      if (depth > 200) throw new SyntaxError("JSON nesting exceeds the view limit");
      space();
      if (text[at] === '"') return string();
      if (text[at] === "[") {
        at++; space(); const out = [];
        if (text[at] === "]") { at++; return out; }
        while (true) {
          out.push(value(depth + 1)); space();
          if (text[at] === "]") { at++; return out; }
          if (text[at++] !== ",") return bad();
        }
      }
      if (text[at] === "{") {
        at++; space(); const out = Object.create(null);
        if (text[at] === "}") { at++; return out; }
        while (true) {
          space(); if (text[at] !== '"') return bad();
          const key = string(); space();
          if (text[at++] !== ":") return bad();
          out[key] = value(depth + 1); space();
          if (text[at] === "}") { at++; return out; }
          if (text[at++] !== ",") return bad();
        }
      }
      for (const [word, literal] of [["true", true], ["false", false], ["null", null]]) {
        if (text.startsWith(word, at)) { at += word.length; return literal; }
      }
      const token = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(text.slice(at))?.[0];
      if (!token) return bad();
      at += token.length;
      if (!/[.eE]/.test(token)) {
        const integer = BigInt(token);
        return integer > BigInt(Number.MAX_SAFE_INTEGER) || integer < BigInt(Number.MIN_SAFE_INTEGER) ? integer : Number(token);
      }
      const number = Number(token);
      if (!Number.isFinite(number)) throw new SyntaxError("Non-finite JSON number");
      return number;
    }
    const result = value(); space();
    if (at !== text.length) return bad();
    return result;
  }
  function stringify(value, pretty = false) {
    const active = new Set();
    function encode(item, depth) {
      if (typeof item === "bigint") return item.toString();
      if (typeof item === "number" && !Number.isFinite(item)) throw new TypeError("JSON numbers must be finite");
      if (item === null || typeof item !== "object") {
        const text = JSON.stringify(item);
        if (text === undefined) throw new TypeError("Unsupported JSON value");
        return text;
      }
      if (active.has(item)) throw new TypeError("Cyclic JSON");
      active.add(item);
      const array = Array.isArray(item);
      const entries = array ? item.map(x => encode(x, depth + 1)) : Object.entries(item).map(([k, v]) => `${JSON.stringify(k)}:${pretty ? " " : ""}${encode(v, depth + 1)}`);
      active.delete(item);
      const open = array ? "[" : "{", close = array ? "]" : "}";
      return open + (pretty && entries.length ? "\n" + entries.map(x => "  ".repeat(depth + 1) + x).join(",\n") + "\n" + "  ".repeat(depth) : entries.join(",")) + close;
    }
    return encode(value, 0);
  }
  const idKey = id => `${typeof id === "string" ? "s" : "i"}:${String(id)}`;
  const idLabel = id => typeof id === "string" ? JSON.stringify(id) : String(id);
  window.AnalyticsWire = Object.freeze({parse, stringify, idKey, idLabel});
})();
