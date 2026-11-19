/* Load the local renderer only when a graph or workflow diagram is opened. */
"use strict";
(() => {
  let pending = null, layouts = null;
  window.GraphMineLayoutLibrary = async () => {
    await window.GraphMineGraphLibrary();
    if (window.GraphMineLayoutsReady) return;
    if (!layouts) layouts = new Promise((resolve, reject) => {
      const script = document.createElement("script"); script.src = "/vendor/graph-layouts.min.js";
      script.onload = () => resolve();
      script.onerror = () => { layouts = null; script.remove(); reject(new Error("Graph layouts could not load. Try again.")); };
      document.head.append(script);
    });
    return layouts;
  };
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
