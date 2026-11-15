/* Load the local renderer only when a graph or workflow diagram is opened. */
"use strict";
(() => {
  let pending = null;
  window.GraphMineGraphLibrary = () => {
    if (window.cytoscape) return Promise.resolve();
    if (pending) return pending;
    pending = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "/vendor/cytoscape.min.js";
      script.onload = () => { if (window.cytoscape) resolve(); else fail(); };
      const fail = () => { pending = null; script.remove(); reject(new Error("The graph renderer could not load. Reopen the result to retry.")); };
      script.onerror = fail;
      document.head.append(script);
    });
    return pending;
  };
})();
