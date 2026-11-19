"use strict";
window.GraphMineOutputs = {
  install({state, api, W, node, runAction}) {
    const $ = id => document.getElementById(id);
    const download = (blob, filename) => {
      const url = URL.createObjectURL(blob), link = node("a", {href: url, download: filename}); link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    for (const [id, title, action] of [
      ["export-csv", "Table with names (CSV)", async () => {
        if (!state.record || !state.port || $("result-port").value === "__result") throw new Error("Choose a saved output table first.");
        const record = state.record;
        const path = `/api/workflows/${record.id}/steps/${encodeURIComponent($("result-step").value)}/ports/${encodeURIComponent($("result-port").value)}/csv?expected_revision=${record.revision}`;
        download(await api(path, {asBlob: true}), `graphmine-${record.id}-revision-${record.revision}-table.csv`);
      }],
      ["export-report", "Full report (ZIP)", async () => {
        if (!state.record || !state.result) throw new Error("Open a saved result first.");
        const record = state.record;
        const step = $("result-step").value, port = $("result-port").value;
        const image = await window.GraphMineWorkspace.visualization.reportImage({workflow: record.id, revision: record.revision, step, port});
        download(await api(`/api/workflows/${record.id}/report`, {method: "POST", body: W.stringify({expected_revision: record.revision, step, port, default_image: image}), asBlob: true}), `graphmine-${record.id}-revision-${record.revision}.zip`);
      }],
    ]) {
      const button = node("button", {id, class: "quiet", type: "button"}, title);
      button.onclick = () => runAction(action); document.querySelector("#result-download-menu .view-menu").insertBefore(button, $(id === "export-csv" ? "view-export-visible" : "download-result"));
    }
    const limits = node("details", {id: "operation-limits", hidden: true}); $("operation-quality").after(limits);
    this.operationLimits = (selected, configuration) => {
      limits.replaceChildren(); limits.hidden = !selected; if (!selected) return;
      limits.append(node("summary", {}, "Supported data and resource limits"), node("p", {}, selected.description || "Input requirements are checked during plan validation."));
      limits.append(node("p", {}, `Input: ${selected.input_kind.replaceAll("_", " ")}. Available compute: ${[selected.execution.cpu && "CPU", selected.execution.gpu && "GPU"].filter(Boolean).join(" and ") || "unavailable"}.`));
      if (selected.gpu_limitations?.length) { const list = node("ul"); for (const text of selected.gpu_limitations) list.append(node("li", {}, text)); limits.append(list); }
      if (configuration) limits.append(node("p", {}, `Server limits: ${(configuration.input_bytes / 1048576).toFixed(0)} MiB of inputs; ${(configuration.result_bytes / 1048576).toFixed(0)} MiB per result artifact; ${configuration.run_timeout_seconds} seconds of run time. ${configuration.memory_admission}`));
      limits.append(node("p", {class: "muted"}, "Each step can also have candidate, output and time budgets. The reviewed plan shows those settings and its memory estimate. Output completeness and algorithm quality are recorded separately."));
      const parameters = node("dl");
      for (const [key, spec] of Object.entries(selected.parameters)) {
        const bounds = [spec.minimum !== undefined ? `minimum ${spec.minimum}` : "", spec.maximum !== undefined ? `maximum ${spec.maximum}` : ""].filter(Boolean);
        if (bounds.length) parameters.append(node("dt", {}, key.replaceAll("_", " ")), node("dd", {}, bounds.join("; ")));
      }
      limits.append(parameters);
    };
  },
};
