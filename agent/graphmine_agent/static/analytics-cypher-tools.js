/* Small lexical helpers: strings, quoted identifiers and comments stay intact. */
(() => {
  "use strict";
  function tokens(text) {
    const result = [];
    let at = 0;
    while (at < text.length) {
      const start = at, char = text[at]; let kind = "symbol";
      if (text.startsWith("//", at)) { kind = "comment"; at = text.indexOf("\n", at); if (at < 0) at = text.length; }
      else if (text.startsWith("/*", at)) { kind = "comment"; const end = text.indexOf("*/", at + 2); at = end < 0 ? text.length : end + 2; }
      else if (["'", '"', "`"].includes(char)) {
        kind = char === "`" ? "identifier" : "literal"; at++;
        while (at < text.length) {
          if (text[at] === "\\" && char !== "`") { at += Math.min(2, text.length - at); continue; }
          if (text[at++] === char) { if (text[at] === char) { at++; continue; } break; }
        }
      } else if (/\s/.test(char)) { kind = "space"; while (at < text.length && /\s/.test(text[at])) at++; }
      else if (/[A-Za-z_]/.test(char)) { kind = "word"; while (at < text.length && /[A-Za-z0-9_]/.test(text[at])) at++; }
      else at++;
      result.push({kind, text: text.slice(start, at), start, end: at});
    }
    return result;
  }
  function parameters(text) {
    const values = tokens(text).filter(t => !["space", "comment"].includes(t.kind)), names = new Set();
    values.forEach((token, index) => {
      if (values[index - 1]?.text === "$" && token.kind === "word") names.add(token.text);
      if (values[index - 1]?.text === "$" && token.kind === "identifier") names.add(token.text.slice(1, -1).replaceAll("``", "`"));
    });
    return [...names];
  }
  function format(text) {
    const clauses = new Set(["MATCH", "OPTIONAL", "WHERE", "WITH", "UNWIND", "RETURN", "ORDER", "SKIP", "LIMIT", "UNION"]);
    let out = "", depth = 0, previous = "";
    for (const token of tokens(text)) {
      if (token.kind === "space") { if (out && !/\s$/.test(out)) out += " "; continue; }
      const clause = token.kind === "word" && depth === 0 && clauses.has(token.text.toUpperCase()) && ![".", ":", "$"].includes(previous);
      if (clause) {
        out = out.trimEnd() + (out.trimEnd() ? previous.toUpperCase() === "OPTIONAL" && token.text.toUpperCase() === "MATCH" ? " " : "\n" : "");
      }
      out += clause ? token.text.toUpperCase() : token.text;
      if (token.kind === "comment" && token.text.startsWith("//")) out += "\n";
      if (token.kind === "symbol") {
        if (["(", "[", "{"].includes(token.text)) depth++;
        if ([")", "]", "}"].includes(token.text)) depth = Math.max(0, depth - 1);
      }
      if (token.kind !== "comment") previous = token.text;
    }
    return out.trim();
  }
  window.GraphMineCypherTools = {tokens, parameters, format};
})();
