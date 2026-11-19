/* Small DOM-only Markdown renderer. Source text is never interpreted as HTML. */
"use strict";
window.GraphMineMarkdown = (text, node) => {
  const root = node("div", {class: "markdown-body"});
  function inline(parent, value) {
    const tokens = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_[^_\n]+_|\[[^\]\n]+\]\([^\s)]+\))/g;
    let offset = 0;
    for (const match of value.matchAll(tokens)) {
      parent.append(document.createTextNode(value.slice(offset, match.index)));
      const token = match[0];
      if (token.startsWith("`")) parent.append(node("code", {}, token.slice(1, -1)));
      else if (token.startsWith("[")) {
        const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
        if (/^(https?:\/\/|#|\/(?!\/))/.test(link[2])) {
          const a = node("a", {href: link[2], ...(link[2].startsWith("http") ? {target: "_blank", rel: "noopener noreferrer"} : {})});
          inline(a, link[1]); parent.append(a);
        } else parent.append(document.createTextNode(link[1]));
      } else {
        const bold = token.startsWith("**") || token.startsWith("__"), tag = node(bold ? "strong" : "em");
        inline(tag, token.slice(bold ? 2 : 1, bold ? -2 : -1)); parent.append(tag);
      }
      offset = match.index + token.length;
    }
    parent.append(document.createTextNode(value.slice(offset)));
  }
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  let paragraph = [], list = null, code = null;
  function flush() { if (paragraph.length) { const p = node("p"); inline(p, paragraph.join(" ")); root.append(p); paragraph = []; } }
  for (const line of lines) {
    if (/^\s*```/.test(line)) { flush(); list = null; if (code) { root.append(node("pre", {}, code.join("\n"))); code = null; } else code = []; continue; }
    if (code) { code.push(line); continue; }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line), item = /^\s*(?:([-*+])|\d+[.)])\s+(.*)$/.exec(line);
    if (heading) { flush(); list = null; const h = node(`h${Math.min(6, heading[1].length + 2)}`); inline(h, heading[2]); root.append(h); }
    else if (item) { flush(); const type = item[1] ? "ul" : "ol"; if (!list || list.tagName.toLowerCase() !== type) { list = node(type); root.append(list); } const li = node("li"); inline(li, item[2]); list.append(li); }
    else if (/^>\s?/.test(line)) { flush(); list = null; const quote = node("blockquote"); inline(quote, line.replace(/^>\s?/, "")); root.append(quote); }
    else if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line)) { flush(); list = null; root.append(node("hr")); }
    else if (!line.trim()) { flush(); list = null; }
    else { list = null; paragraph.push(line.trim()); }
  }
  flush(); if (code) root.append(node("pre", {}, code.join("\n")));
  return root;
};
