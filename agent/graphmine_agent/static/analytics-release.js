/* Preserve drafts when the server is upgraded underneath an open tab. */
"use strict";
(() => {
  const build = document.querySelector('meta[name="graphmine-build"]')?.getAttribute("content");
  if (!build) return;
  let pending = false, notified = false;
  async function check() {
    if (document.hidden || pending || notified) return;
    pending = true;
    try {
      const response = await fetch("/api/build", {cache: "no-store"});
      if (!response.ok) return;
      const current = await response.json();
      if (typeof current.build_id !== "string" || current.build_id === build) return;
      notified = true;
      const banner = document.createElement("aside");
      banner.id = "release-update"; banner.className = "notice"; banner.setAttribute("role", "status");
      banner.append(document.createTextNode("An update is available. Save your draft before reloading. "));
      const reload = document.createElement("button");
      reload.type = "button"; reload.textContent = "Reload workspace";
      reload.onclick = () => location.reload(); banner.append(reload);
      document.body.prepend(banner);
    } catch { /* A temporary outage should not disturb the current workspace. */ }
    finally { pending = false; }
  }
  document.addEventListener("visibilitychange", check);
  window.addEventListener("online", check);
  setInterval(check, 60000);
  void check();
})();
