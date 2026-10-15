"use strict";
(async () => {
  const status = document.getElementById("share-status");
  try {
    const token = location.hash.slice(1); if (!token) throw new Error("Open the complete link supplied by the project owner.");
    const response = await fetch("/api/shared/read", {method: "POST", credentials: "omit", headers: {"Content-Type": "application/json"}, body: JSON.stringify({token})});
    const item = window.AnalyticsWire.parse(await response.text()); if (!response.ok) throw new Error(item.error?.message || "This link is unavailable.");
    window.GraphMineProjectViewer.show(document.getElementById("shared-viewer"), item); status.textContent = "Read-only snapshot. No calculations run on this page.";
  } catch (error) { status.textContent = error.message; }
})();
