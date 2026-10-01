(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const state = {
    base: localStorage.getItem("graphmine.apiBase") || "",
    token: localStorage.getItem("graphmine.apiToken") || "",
    domains: [], session: null, files: [], graphId: null,
    result: null, graphPreview: null, socket: null, lastEvent: 0,
  };

  const domainGlyphs = ["◇", "⌁", "✣", "⌾", "◎", "▦", "◈", "⌬", "↝"];

  function headers(json = true) {
    const value = json ? {"Content-Type": "application/json"} : {};
    if (state.token) value.Authorization = `Bearer ${state.token}`;
    return value;
  }

  async function api(path, options = {}) {
    const response = await fetch(`${state.base}${path}`, {
      ...options,
      headers: {...headers(!(options.body instanceof FormData)), ...(options.headers || {})},
    });
    let body = null;
    try { body = await response.json(); } catch (_) { body = {}; }
    if (!response.ok) {
      const detail = body.error?.message || body.detail?.message || body.detail || response.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return body;
  }

  function toast(message, error = false) {
    const node = $("#toast");
    node.textContent = message;
    node.className = `toast show${error ? " error" : ""}`;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.className = "toast", 3500);
  }

  function escape(value) {
    return String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  }

  async function loadDomains() {
    try {
      state.domains = await api("/api/domains");
      $("#domain-grid").innerHTML = state.domains.map((domain, index) => `
        <button class="domain-card" data-domain="${escape(domain.id)}">
          <span class="domain-icon">${domainGlyphs[index % domainGlyphs.length]}</span>
          <h2>${escape(domain.name)}</h2><p>${escape(domain.description)}</p>
        </button>`).join("");
      document.querySelectorAll(".domain-card").forEach(card => card.addEventListener("click", () => startSession(card.dataset.domain)));
      await health();
    } catch (error) {
      $("#domain-grid").innerHTML = `<div class="loading-card">Could not reach the GraphMine server. Open connection settings and check the API address or token.</div>`;
      setStatus("Offline", "degraded"); toast(error.message, true);
    }
  }

  async function health() {
    const report = await api("/api/health");
    setStatus(report.status === "ready" ? "Server ready" : "Server degraded", report.status === "ready" ? "ready" : "degraded");
    $("#graphmine-state").textContent = report.graphmine.binary_available && !report.graphmine.error ? `${report.graphmine.compiled_backend_count} backends` : "Unavailable";
    $("#llm-state").textContent = report.llm.enabled ? report.llm.model.split("/").pop() : "Offline fallback";
  }

  function setStatus(label, kind) {
    const node = $("#server-status"); node.textContent = label; node.className = `status status-${kind}`;
  }

  async function startSession(domainId) {
    const title = $("#session-title").value.trim() || null;
    try {
      state.session = await api("/api/sessions", {method:"POST", body:JSON.stringify({domain_id:domainId, title})});
      const domain = state.domains.find(item => item.id === domainId);
      $("#active-domain").textContent = domain.name;
      $("#active-domain-description").textContent = domain.description;
      $("#workspace-title").textContent = title || "New analysis";
      $("#domain-view").classList.add("hidden"); $("#workspace-view").classList.remove("hidden");
      connectEvents(); await health();
    } catch (error) { toast(error.message, true); }
  }

  function connectEvents() {
    if (state.socket) state.socket.close();
    const origin = state.base || window.location.origin;
    const url = new URL(`/api/sessions/${state.session.id}/events/ws`, origin);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.searchParams.set("after", state.lastEvent);
    const protocols = ["graphmine"];
    if (state.token) {
      const bytes = new TextEncoder().encode(state.token);
      let binary = "";
      bytes.forEach(byte => binary += String.fromCharCode(byte));
      const encoded = btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
      protocols.push(`graphmine.token.${encoded}`);
    }
    state.socket = new WebSocket(url, protocols);
    state.socket.onmessage = event => {
      const value = JSON.parse(event.data);
      if (value.type === "heartbeat") return;
      state.lastEvent = Math.max(state.lastEvent, value.sequence || 0);
      handleEvent(value);
    };
    state.socket.onclose = () => {
      if (state.session) setTimeout(connectEvents, 1800);
    };
  }

  function handleEvent(event) {
    const labels = {"job.queued":"Queued for GPU", "job.running":"Running on GPU", "job.interpreting":"Interpreting result", "job.completed":"Complete", "job.failed":"Failed", "job.cancelled":"Cancelled"};
    const node = $("#job-state"); node.textContent = labels[event.type] || event.type; node.classList.remove("hidden");
    if (event.type === "job.completed") loadResult(event.payload.result_id);
    if (event.type === "job.failed") { toast(event.payload.error?.message || "GPU job failed", true); addMessage("assistant", event.payload.error?.message || "The GPU job failed."); }
  }

  async function upload(files) {
    if (!state.session) return;
    for (const file of files) {
      const data = new FormData(); data.append("file", file); data.append("role", $("#file-role").value); data.append("directed", $("#directed").checked);
      try {
        toast(`Uploading ${file.name}…`);
        const record = await api(`/api/sessions/${state.session.id}/files`, {method:"POST", body:data});
        state.files.push(record); if (record.role === "graph") state.graphId = record.id;
        renderFiles(); toast(`${file.name} is ready`);
      } catch (error) { toast(`${file.name}: ${error.message}`, true); }
    }
  }

  function renderFiles() {
    $("#file-list").innerHTML = state.files.map(file => `<div class="file-item" title="${escape(file.id)}"><span>${escape(file.original_name)}</span><em>${escape(file.role.replaceAll("_", " "))}</em></div>`).join("");
  }

  function addMessage(role, content, plan = null) {
    const article = document.createElement("article"); article.className = `message ${role}`;
    const planHtml = plan ? `<div class="plan-card"><strong>Validated execution plan</strong><div class="plan-grid"><span>Problem</span><b>${escape(plan.problem_id)}</b><span>Operation</span><b>${escape(plan.operation_id)}</b><span>Backend</span><b>${escape(plan.backend_id)}</b>${Object.keys(plan.parameters || {}).length ? `<span>Parameters</span><b>${escape(JSON.stringify(plan.parameters))}</b>` : ""}${plan.missing_inputs?.length ? `<span>Needs</span><b>${escape(plan.missing_inputs.join(", "))}</b>` : ""}</div></div>` : "";
    article.innerHTML = `<div class="avatar">${role === "user" ? "Y" : "G"}</div><div class="bubble"><p>${escape(content).replaceAll("\n", "<br>")}</p>${planHtml}</div>`;
    $("#messages").appendChild(article); $("#messages").scrollTop = $("#messages").scrollHeight;
  }

  async function sendChat(message) {
    if (!state.session) return;
    addMessage("user", message); $("#send-button").disabled = true;
    try {
      const response = await api(`/api/sessions/${state.session.id}/chat`, {method:"POST", body:JSON.stringify({message, graph_id:state.graphId, result_id:state.result?.id || null, mode:"auto", execute:$("#execute-toggle").checked})});
      addMessage("assistant", response.message, response.plan);
      if (response.interpretation && response.result_id) await loadResult(response.result_id, false);
      if (response.job_id) { $("#job-state").textContent = "Queued for GPU"; $("#job-state").classList.remove("hidden"); }
    } catch (error) { addMessage("assistant", `I couldn't complete that request: ${error.message}`); toast(error.message, true); }
    finally { $("#send-button").disabled = false; }
  }

  async function loadResult(resultId, announce = true) {
    try {
      state.result = await api(`/api/results/${resultId}`);
      try {
        const job = await api(`/api/jobs/${state.result.job_id}`);
        state.graphPreview = await api(`/api/files/${job.plan.graph_id}/graph-preview?vertex_limit=500&edge_limit=2000`);
      } catch (_) { state.graphPreview = null; }
      renderResult();
      if (announce) addMessage("assistant", state.result.interpretation?.summary || "The GPU computation is complete. The structured result is ready.");
    } catch (error) { toast(error.message, true); }
  }

  function resolvePath(object, path) {
    return path.split(".").filter(Boolean).reduce((value, key) => value != null && Object.prototype.hasOwnProperty.call(value, key) ? value[key] : undefined, object);
  }

  function renderResult() {
    const result = state.result, interpretation = result.interpretation;
    $("#insight-column").classList.remove("empty"); $("#empty-insights").classList.add("hidden"); $("#result-content").classList.remove("hidden");
    $("#result-title").textContent = result.operation_id.replaceAll("-", " ").replace(/\b\w/g, c => c.toUpperCase());
    $("#raw-result").textContent = JSON.stringify(result.payload, null, 2);
    if (interpretation) {
      $("#interpretation").innerHTML = `<p>${escape(interpretation.summary)}</p>${listSection("Key findings", interpretation.findings)}${listSection("Limitations", interpretation.limitations)}${listSection("Try next", interpretation.suggested_followups)}`;
      $("#visualizations").innerHTML = "";
      interpretation.visualizations.forEach(spec => renderVisualization(spec, resolvePath(result.payload, spec.data_ref)));
    } else {
      $("#interpretation").innerHTML = "<p>The computation completed; interpretation is not yet available.</p>";
    }
  }

  function listSection(title, items) {
    return items?.length ? `<h3>${escape(title)}</h3><ul>${items.map(item => `<li>${escape(item)}</li>`).join("")}</ul>` : "";
  }

  function renderVisualization(spec, data) {
    const card = document.createElement("section"); card.className = "viz-card";
    const previewNote = spec.type === "network" && state.graphPreview && (state.graphPreview.vertices_truncated || state.graphPreview.edges_truncated)
      ? ` Preview shows ${state.graphPreview.vertices.length}/${state.graphPreview.vertex_count} vertices and ${state.graphPreview.edges.length}/${state.graphPreview.edge_count} edges.` : "";
    card.innerHTML = `<div class="viz-head"><div><h3>${escape(spec.title)}</h3><p>${escape((spec.description || spec.data_ref) + previewNote)}</p></div><span class="viz-kind">${escape(spec.type)}</span></div><div class="viz-body"></div>`;
    const body = card.querySelector(".viz-body");
    if (spec.type === "metric_cards") renderMetrics(body, data, spec.encodings);
    else if (["bar", "histogram"].includes(spec.type)) renderBars(body, data, spec);
    else if (spec.type === "line") renderLine(body, data, spec);
    else if (spec.type === "timeline") renderTimeline(body, data, spec);
    else if (spec.type === "heatmap") renderHeatmap(body, data, spec);
    else if (spec.type === "network") renderNetwork(body, data, spec);
    else renderTable(body, data, spec.limit || 1000);
    $("#visualizations").appendChild(card);
  }

  function rowsFrom(data) {
    if (Array.isArray(data)) return data.map((value, index) => typeof value === "object" && value !== null ? {index, ...value} : {index, value});
    if (data && typeof data === "object") return Object.entries(data).map(([key, value]) => typeof value === "object" && value !== null && !Array.isArray(value) ? {key, ...value} : {key, value});
    return [{value:data}];
  }

  function pick(row, field) {
    if (!field) return undefined;
    if (field.endsWith(".length")) { const value = pick(row, field.slice(0,-7)); return value?.length; }
    return field.split(".").reduce((value,key) => value?.[key], row);
  }

  function renderMetrics(body, data, encodings) {
    const entries = Object.entries(encodings || {}).map(([label, field]) => [label, pick(data, field)]).filter(([,value]) => value !== undefined);
    const values = entries.length ? entries : Object.entries(data || {}).filter(([,value]) => ["number","string","boolean"].includes(typeof value)).slice(0,12);
    body.innerHTML = `<div class="metric-grid">${values.map(([label,value]) => `<div class="metric"><strong>${escape(formatValue(value))}</strong><span>${escape(label.replaceAll("_"," "))}</span></div>`).join("")}</div>`;
  }

  function renderBars(body, data, spec) {
    const rows = rowsFrom(data).slice(0, spec.limit || 80), category = spec.encodings?.category || spec.encodings?.x, valueField = spec.encodings?.value || spec.encodings?.y;
    let points = rows.map((row,index) => {
      const numeric = Number(pick(row,valueField) ?? row.value ?? Object.values(row).find(value => typeof value === "number") ?? 0);
      return {label:String(pick(row,category) ?? row.key ?? row.vertex ?? row.index ?? index), value:Number.isFinite(numeric) ? numeric : 0};
    });
    if (spec.type === "histogram") {
      const counts = new Map(); points.forEach(point => counts.set(point.value, (counts.get(point.value)||0)+1)); points = [...counts].map(([label,value]) => ({label:String(label),value})).sort((a,b)=>Number(a.label)-Number(b.label));
    }
    if (!points.length) { body.textContent = "No values to plot."; return; }
    const width=620,height=230,pad=35,max=Math.max(...points.map(p=>Math.abs(p.value)),1),barWidth=Math.max(3,(width-pad*2)/points.length-3);
    body.innerHTML = `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(spec.title)}"><line class="axis" x1="${pad}" y1="${height-pad}" x2="${width-pad/2}" y2="${height-pad}"/>${points.map((point,index)=>{const h=Math.abs(point.value)/max*(height-pad*2);const x=pad+index*((width-pad*2)/points.length);return `<rect class="bar" x="${x}" y="${height-pad-h}" width="${barWidth}" height="${h}"><title>${escape(point.label)}: ${escape(point.value)}</title></rect>${points.length<18?`<text x="${x}" y="${height-17}" transform="rotate(30 ${x} ${height-17})">${escape(point.label.slice(0,10))}</text>`:""}`}).join("")}</svg>`;
  }

  function numericSeries(data, spec, limit = 200) {
    const rows = rowsFrom(data).slice(0, spec.limit || limit);
    const xField = spec.encodings?.x || spec.encodings?.time;
    const yField = spec.encodings?.y || spec.encodings?.value;
    return rows.map((row, index) => {
      const candidate = pick(row, yField) ?? row.value ?? Object.values(row).find(value => typeof value === "number");
      const value = Number(candidate);
      return {
        label: String(pick(row, xField) ?? row.key ?? row.vertex ?? row.index ?? index),
        value,
      };
    }).filter(point => Number.isFinite(point.value));
  }

  function renderLine(body, data, spec) {
    const points = numericSeries(data, spec);
    if (!points.length) { renderTable(body, data, spec.limit || 100); return; }
    const width=620,height=240,pad=38,min=Math.min(...points.map(point=>point.value)),max=Math.max(...points.map(point=>point.value)),span=max-min||1;
    const positioned=points.map((point,index)=>({...point,x:pad+(points.length===1?0.5:index/(points.length-1))*(width-pad*2),y:height-pad-(point.value-min)/span*(height-pad*2)}));
    body.innerHTML=`<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(spec.title)}"><line class="axis" x1="${pad}" y1="${height-pad}" x2="${width-pad}" y2="${height-pad}"/><polyline class="line-series" points="${positioned.map(point=>`${point.x},${point.y}`).join(" ")}"/>${positioned.map(point=>`<circle class="line-point" cx="${point.x}" cy="${point.y}" r="4"><title>${escape(point.label)}: ${escape(point.value)}</title></circle>`).join("")}<text x="4" y="${pad}">${escape(max)}</text><text x="4" y="${height-pad}">${escape(min)}</text></svg>`;
  }

  function renderTimeline(body, data, spec) {
    const rows=rowsFrom(data).slice(0,spec.limit||30);
    const eventField=spec.encodings?.events||spec.encodings?.edges||"edges_in_temporal_order";
    const sequences=rows.map((row,index)=>{
      const events=pick(row,eventField)??row.edges_in_temporal_order??row.timestamps;
      return {label:String(row.id??row.key??row.index??index),events:Array.isArray(events)?events:[]};
    }).filter(row=>row.events.length);
    if(!sequences.length){renderTable(body,data,spec.limit||100);return;}
    const width=620,pad=65,rowHeight=34,height=Math.max(130,sequences.length*rowHeight+45),maximum=Math.max(...sequences.map(row=>row.events.length),2);
    body.innerHTML=`<svg class="chart timeline-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(spec.title)}">${sequences.map((row,rowIndex)=>{const y=28+rowIndex*rowHeight;return `<text x="5" y="${y+4}">${escape(row.label.slice(0,9))}</text><line class="timeline-track" x1="${pad}" y1="${y}" x2="${width-20}" y2="${y}"/>${row.events.map((event,eventIndex)=>{const x=pad+(eventIndex/(maximum-1))*(width-pad-25);return `<circle class="timeline-event" cx="${x}" cy="${y}" r="5"><title>${escape(formatValue(event))}</title></circle><text x="${x-3}" y="${y-9}">${eventIndex+1}</text>`}).join("")}`}).join("")}</svg>`;
  }

  function renderHeatmap(body, data, spec) {
    let labels=[],columns=[],matrix=[];
    if(Array.isArray(data)&&data.every(row=>Array.isArray(row))){matrix=data;labels=data.map((_,index)=>String(index));columns=(data[0]||[]).map((_,index)=>String(index));}
    else {
      const rows=rowsFrom(data).slice(0,spec.limit||25);
      columns=[...new Set(rows.flatMap(row=>Object.keys(row).filter(key=>Number.isFinite(Number(row[key])))))].slice(0,20);
      labels=rows.map((row,index)=>String(row.key??row.vertex??row.index??index));
      matrix=rows.map(row=>columns.map(column=>Number(row[column])));
    }
    matrix=matrix.slice(0,25).map(row=>row.slice(0,20));labels=labels.slice(0,matrix.length);columns=columns.slice(0,matrix[0]?.length||0);
    const values=matrix.flat().filter(Number.isFinite);
    if(!values.length){renderTable(body,data,spec.limit||100);return;}
    const max=Math.max(...values.map(Math.abs),1),cell=Math.max(13,Math.min(25,500/Math.max(columns.length,1))),left=90,top=32,width=left+columns.length*cell+15,height=top+matrix.length*cell+20;
    body.innerHTML=`<div class="heatmap-wrap"><svg class="chart heatmap-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(spec.title)}">${columns.map((column,index)=>`<text x="${left+index*cell+cell/2}" y="20" text-anchor="middle">${escape(column.slice(0,7))}</text>`).join("")}${matrix.map((row,rowIndex)=>`<text x="${left-7}" y="${top+rowIndex*cell+cell*.7}" text-anchor="end">${escape(labels[rowIndex].slice(0,12))}</text>${row.map((value,columnIndex)=>{const opacity=.12+.82*Math.abs(value)/max;const fill=value<0?`rgba(238,123,45,${opacity})`:`rgba(22,115,75,${opacity})`;return `<rect class="heat-cell" x="${left+columnIndex*cell}" y="${top+rowIndex*cell}" width="${cell-1}" height="${cell-1}" style="fill:${fill}"><title>${escape(labels[rowIndex])} · ${escape(columns[columnIndex])}: ${escape(value)}</title></rect>`}).join("")}`).join("")}</svg></div>`;
  }

  function networkData(data) {
    let rawNodes=[], rawEdges=[];
    const preview = state.graphPreview;
    if (Array.isArray(data)) {
      const first = data[0];
      if (first && typeof first === "object" && !Array.isArray(first) && first.vertex !== undefined) {
        rawNodes = data.map(row => ({
          id: String(row.vertex),
          value: row.community ?? row.core_number ?? row.score ?? row.count,
        }));
      } else {
        const selection = Array.isArray(first)
          ? first
          : [...(first?.vertices || first?.clique || first?.left || []), ...(first?.right || [])];
        rawNodes = selection.map(value => ({id:String(value)}));
      }
      if (first?.edges) rawEdges = first.edges;
    } else if (data && typeof data === "object") rawNodes = Object.entries(data).map(([id,value]) => ({id, value:typeof value === "object" ? JSON.stringify(value) : value}));
    if (preview) {
      const values = new Map(rawNodes.map(node => [String(node.id), node.value]));
      const selected = new Set(rawNodes.map(node => String(node.id)));
      const useSelection = selected.size > 0 && selected.size < preview.vertices.length;
      rawNodes = preview.vertices
        .filter(vertex => !useSelection || selected.has(String(vertex.id)))
        .map(vertex => ({id:String(vertex.id), value:values.get(String(vertex.id))}));
      const nodeIds = new Set(rawNodes.map(node => node.id));
      rawEdges = preview.edges.filter(edge => nodeIds.has(String(edge.source)) && nodeIds.has(String(edge.target)));
    }
    rawNodes = rawNodes.slice(0,120);
    const visible = new Set(rawNodes.map(node => node.id));
    rawEdges = rawEdges.filter(edge => visible.has(String(edge.source??edge[0])) && visible.has(String(edge.target??edge[1])));
    return {nodes:rawNodes,edges:rawEdges};
  }

  function renderNetwork(body, data, spec) {
    const {nodes,edges}=networkData(data); if(!nodes.length){renderTable(body,data,spec.limit||100);return;}
    const width=620,height=310,cx=width/2,cy=height/2,r=Math.min(width,height)*.35;
    const positioned=nodes.map((node,i)=>({...node,x:cx+Math.cos(i/nodes.length*Math.PI*2)*r,y:cy+Math.sin(i/nodes.length*Math.PI*2)*r})); const byId=new Map(positioned.map(n=>[String(n.id),n]));
    const palette=["#16734b","#ee7b2d","#3e9b72","#d6a029","#577f69","#b7562e","#57a89a"];
    const color=value=>{const text=String(value??"");let hash=0;for(const character of text)hash=(hash*31+character.charCodeAt(0))>>>0;return palette[hash%palette.length]};
    body.innerHTML=`<div class="network-stage"><svg class="chart" viewBox="0 0 ${width} ${height}"><g class="network-transform">${edges.map(edge=>{const a=byId.get(String(edge.source??edge[0])),b=byId.get(String(edge.target??edge[1]));return a&&b?`<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`:""}).join("")}${positioned.map(node=>{const radius=spec.encodings?.node_size?6+Math.min(8,Math.abs(Number(node.value))||0):7;const fill=spec.encodings?.node_color?color(node.value):"#16734b";return `<g><circle cx="${node.x}" cy="${node.y}" r="${radius}" style="fill:${fill}"><title>${escape(node.id)}${node.value!==undefined?`: ${escape(node.value)}`:""}</title></circle>${nodes.length<35?`<text x="${node.x+8}" y="${node.y+3}">${escape(node.id.slice(0,12))}</text>`:""}</g>`}).join("")}</g></svg></div>`;
    body.querySelectorAll("circle").forEach(circle=>circle.addEventListener("click",()=>circle.classList.toggle("selected")));
    enablePanZoom(body.querySelector("svg"),body.querySelector(".network-transform"));
  }

  function enablePanZoom(svg,group) {
    let scale=1,x=0,y=0,drag=null; const apply=()=>group.setAttribute("transform",`translate(${x} ${y}) scale(${scale})`);
    svg.addEventListener("wheel",event=>{event.preventDefault();scale=Math.min(4,Math.max(.5,scale*(event.deltaY<0?1.12:.89)));apply()},{passive:false});
    svg.addEventListener("pointerdown",event=>{drag={x:event.clientX-x,y:event.clientY-y};svg.setPointerCapture(event.pointerId)});
    svg.addEventListener("pointermove",event=>{if(drag){x=event.clientX-drag.x;y=event.clientY-drag.y;apply()}}); svg.addEventListener("pointerup",()=>drag=null);
  }

  function renderTable(body, data, limit) {
    const rows=rowsFrom(data).slice(0,limit), keys=[...new Set(rows.flatMap(row=>Object.keys(row)))].slice(0,15);
    body.innerHTML=`<input class="viz-filter" placeholder="Filter rows…"><div class="table-wrap"><table class="data-table"><thead><tr>${keys.map(key=>`<th>${escape(key)}</th>`).join("")}</tr></thead><tbody>${tableRows(rows,keys)}</tbody></table></div>`;
    body.querySelector("input").addEventListener("input",event=>{const match=event.target.value.toLowerCase();body.querySelector("tbody").innerHTML=tableRows(rows.filter(row=>JSON.stringify(row).toLowerCase().includes(match)),keys)});
  }

  function tableRows(rows,keys){return rows.map(row=>`<tr>${keys.map(key=>`<td title="${escape(formatValue(row[key]))}">${escape(formatValue(row[key]))}</td>`).join("")}</tr>`).join("")}
  function formatValue(value){if(value===null||value===undefined)return "—";if(typeof value==="object")return JSON.stringify(value);if(typeof value==="number")return Number.isInteger(value)?String(value):value.toLocaleString(undefined,{maximumSignificantDigits:6});return String(value)}

  $("#chat-form").addEventListener("submit", event => { event.preventDefault(); const input=$("#chat-input"),message=input.value.trim(); if(message){input.value="";sendChat(message);} });
  $("#chat-input").addEventListener("keydown", event => { if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();$("#chat-form").requestSubmit();} });
  $("#file-input").addEventListener("change", event => upload(event.target.files));
  const drop=$("#drop-zone"); ["dragenter","dragover"].forEach(name=>drop.addEventListener(name,event=>{event.preventDefault();drop.classList.add("dragging")})); ["dragleave","drop"].forEach(name=>drop.addEventListener(name,event=>{event.preventDefault();drop.classList.remove("dragging")})); drop.addEventListener("drop",event=>upload(event.dataTransfer.files));
  $("#new-session").addEventListener("click",()=>{if(state.socket)state.socket.close();state.session=null;state.files=[];state.graphId=null;state.result=null;state.graphPreview=null;$("#workspace-view").classList.add("hidden");$("#domain-view").classList.remove("hidden")});
  $("#raw-toggle").addEventListener("click",()=>$("#raw-result").classList.toggle("hidden"));
  $("#settings-button").addEventListener("click",()=>{$("#api-base").value=state.base;$("#api-token").value=state.token;$("#settings-dialog").showModal()});
  $("#save-settings").addEventListener("click",()=>{state.base=$("#api-base").value.trim().replace(/\/$/,"");state.token=$("#api-token").value;localStorage.setItem("graphmine.apiBase",state.base);localStorage.setItem("graphmine.apiToken",state.token);setTimeout(loadDomains,0)});

  loadDomains();
})();
