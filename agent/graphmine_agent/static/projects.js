"use strict";
(async () => {
  const $ = id => document.getElementById(id), W = window.AnalyticsWire, {node, show} = window.GraphMineProjectViewer;
  let project, item, viewer, user, pending = false;
  async function api(path, method = "GET", body) { const response = await fetch(path, {method, headers: {"Content-Type": "application/json"}, ...(body ? {body: W.stringify(body)} : {})}); const text = await response.text(), value = text ? W.parse(text) : null; if (!response.ok) throw new Error(value?.error?.message || "The request failed."); return value; }
  async function action(work) { if (pending) return; pending = true; $("project-notice").textContent = ""; try { await work(); } catch (error) { $("project-notice").textContent = error.message; } finally { pending = false; } }
  async function refresh(selected = $("project-choice").value) { const projects = await api("/api/projects"); $("project-choice").replaceChildren(node("option", {value: ""}, "Choose a project"), ...projects.map(p => node("option", {value: p.id}, `${p.name} · ${p.role}`))); $("project-choice").value = selected; await loadProject(); }
  async function loadProject() {
    viewer?.destroy(); $("item-panel").hidden = true; item = null; const id = $("project-choice").value; $("project-detail").hidden = !id; if (!id) return;
    project = await api(`/api/projects/${id}`); $("project-title").textContent = project.name; $("project-role").textContent = `Your role: ${project.role}`;
    $("member-form").hidden = $("delete-project").hidden = project.role !== "owner";
    $("project-members").replaceChildren();
    for (const member of project.members) { const row = node("p", {}, `${member.username} · ${member.role}`); if (project.role === "owner") { const remove = node("button", {type: "button", class: "quiet"}, "Remove member"); remove.onclick = () => action(async () => { await api(`/api/projects/${id}/members/${member.user_id}`, "DELETE"); await loadProject(); }); row.append(remove); } $("project-members").append(row); }
    $("project-item").replaceChildren(node("option", {value: ""}, "Choose a snapshot"), ...project.items.map(i => node("option", {value: i.id}, `${i.name} · ${i.kind}`)));
  }
  async function loadItem() {
    viewer?.destroy(); const id = $("project-item").value; $("item-panel").hidden = !id; if (!id) return;
    item = await api(`/api/project-items/${id}`); viewer = show($("shared-viewer"), item);
    $("annotation-form").hidden = $("view-form").hidden = item.role === "viewer"; $("link-controls").hidden = item.role !== "owner"; $("created-link-label").hidden = true;
    $("project-notes").replaceChildren(node("h2", {}, "Annotations and saved views"));
    for (const note of item.notes) { const row = node("article", {}, `${note.author} · ${new Date(note.created_at).toLocaleString()}`);
      if (note.kind === "annotation") row.append(node("p", {}, note.text)); else { const button = node("button", {type: "button", class: "secondary", "data-view-id": note.id}, note.name); button.onclick = () => viewer.apply(note); row.append(button); }
      if (item.role === "owner" || item.role === "editor" && note.author_id === user.id) { const remove = node("button", {type: "button", class: "quiet"}, "Delete"); remove.onclick = () => action(async () => { await api(`/api/project-notes/${note.id}`, "DELETE"); await loadItem(); }); row.append(remove); }
      $("project-notes").append(row);
    }
    $("project-links").replaceChildren(); for (const link of item.links) { const row = node("p", {}, `Link expires ${new Date(link.expires_at * 1000).toLocaleString()}`), revoke = node("button", {type: "button", class: "quiet", "data-revoke-link": link.id}, "Revoke link"); revoke.onclick = () => action(async () => { await api(`/api/project-links/${link.id}`, "DELETE"); await loadItem(); }); row.append(revoke); $("project-links").append(row); }
  }
  $("create-project").onsubmit = event => { event.preventDefault(); action(async () => { const p = await api("/api/projects", "POST", {name: $("project-name").value}); $("project-name").value = ""; await refresh(p.id); }); };
  $("project-choice").onchange = () => action(loadProject); $("project-item").onchange = () => action(loadItem);
  $("member-form").onsubmit = event => { event.preventDefault(); action(async () => { await api(`/api/projects/${project.id}/members`, "POST", {username: $("member-name").value, role: $("member-role").value}); await loadProject(); }); };
  $("annotation-form").onsubmit = event => { event.preventDefault(); action(async () => { await api(`/api/project-items/${item.id}/annotations`, "POST", {text: $("annotation-text").value}); $("annotation-text").value = ""; await loadItem(); }); };
  $("view-form").onsubmit = event => { event.preventDefault(); action(async () => { await api(`/api/project-items/${item.id}/views`, "POST", {name: $("view-name").value, ...viewer.capture()}); $("view-name").value = ""; await loadItem(); }); };
  $("link-form").onsubmit = event => { event.preventDefault(); action(async () => { const link = await api(`/api/project-items/${item.id}/links`, "POST", {days: Number($("link-days").value)}); await loadItem(); $("created-link").value = new URL(link.url, location.origin).href; $("created-link-label").hidden = false; $("created-link").select(); }); };
  $("delete-item").onclick = () => { if (confirm("Delete this shared snapshot, annotations, views and links? Imported copies remain available.")) action(async () => { await api(`/api/project-items/${item.id}`, "DELETE"); await loadProject(); }); };
  $("delete-project").onclick = () => { if (confirm("Delete this project, its shared snapshots, discussions and links? Private conversations and imported copies remain available.")) action(async () => { await api(`/api/projects/${project.id}`, "DELETE"); await refresh(""); }); };
  try { if (!await window.GraphMineAccount.ready) throw new Error("Project collaboration requires account login to be enabled."); user = (await api("/api/auth/me")).user; await refresh(); } catch (error) { $("project-notice").textContent = error.message; }
})();
