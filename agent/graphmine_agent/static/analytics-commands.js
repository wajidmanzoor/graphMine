/* Local commands, annotations and downloads for the conversation workspace. */
"use strict";
window.GraphMineCommands = ({state, api, W, node, notice, runAction, ensureSession, renderConversation, updateControls}) => {
  const $ = id => document.getElementById(id);
  const input = $("question"), menu = $("command-menu"), list = $("command-options");
  const catalog = [
    {name: "help", usage: "", description: "Show all commands"},
    {name: "feedback", usage: "note [| expected answer]", description: "Flag an issue with an answer"},
    {name: "correct", usage: "expected answer", description: "Save a corrected answer"},
    {name: "rate", usage: "1–5 [note]", description: "Rate the last answer"},
    {name: "note", usage: "observation", description: "Save a research note"},
    {name: "export", usage: "", description: "Download this conversation and its evidence"},
    {name: "status", usage: "", description: "Show the model and app version"},
  ];
  let matches = [], active = 0, feedbackTarget = null;
  const isCommand = message => /^[\/\\]/.test(message.trimStart());
  function close() {
    menu.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }
  function highlight() {
    [...list.children].forEach((option, index) => option.setAttribute("aria-selected", String(index === active)));
    const option = list.children[active];
    if (option) { input.setAttribute("aria-activedescendant", option.id); option.scrollIntoView({block: "nearest"}); }
  }
  function select(index) {
    const prefix = input.value.trimStart().startsWith("\\") ? "\\" : "/";
    input.value = `${prefix}${matches[index].name} `;
    input.focus(); input.setSelectionRange(input.value.length, input.value.length);
    close(); updateControls(); window.GraphMineShell.resizeComposer();
  }
  function suggest() {
    const match = /^\s*[\/\\]([^\s]*)$/.exec(input.value);
    if (!match || document.activeElement !== input) { close(); return; }
    matches = catalog.filter(command => command.name.startsWith(match[1].toLowerCase()));
    if (!matches.length) { close(); return; }
    active = 0; list.replaceChildren();
    matches.forEach((command, index) => {
      const option = node("li", {id: `command-option-${command.name}`, role: "option", "aria-selected": "false"});
      const heading = node("span", {class: "command-title"});
      heading.append(node("strong", {}, `/${command.name}`), node("span", {}, command.usage));
      option.append(heading, node("span", {class: "command-description"}, command.description));
      option.addEventListener("pointerdown", event => event.preventDefault());
      option.addEventListener("click", () => select(index));
      list.append(option);
    });
    menu.hidden = false; input.setAttribute("aria-expanded", "true"); highlight();
  }
  input.addEventListener("input", () => { suggest(); updateControls(); });
  input.addEventListener("focus", suggest);
  input.addEventListener("blur", close);
  input.addEventListener("keydown", event => {
    if (menu.hidden || event.isComposing || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return;
    if (!["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Escape") close();
    else if (event.key === "Enter" || event.key === "Tab") select(active);
    else { active = (active + (event.key === "ArrowDown" ? 1 : -1) + matches.length) % matches.length; highlight(); }
  });
  function update() {
    const count = state.feedbackCount || 0;
    $("conversation-feedback-count").textContent = `${count} saved annotation${count === 1 ? "" : "s"}`;
    for (const id of ["conversation-help", "conversation-feedback", "conversation-export", "conversation-export-feedback", "save-conversation-feedback"])
      $(id).disabled = state.busy || !state.session;
  }
  async function download(path, filename) {
    const blob = await api(path, {asBlob: true});
    const url = URL.createObjectURL(blob), anchor = node("a", {href: url, download: filename});
    document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function send(message) {
    await ensureSession(); close();
    const id = state.session.id;
    const response = await api(`/api/sessions/${id}/chat`, {method: "POST", body: W.stringify({message})});
    if (input.value.trim() === message) input.value = "";
    // Use the saved transcript so command replies survive navigation and reload.
    const workspace = await api(`/api/sessions/${id}/workspace`);
    if (state.session?.id !== id) return;
    state.legacyMessages = workspace.messages;
    state.feedbackCount = workspace.feedback_count || 0;
    state.lastChatKey = null;
    renderConversation(); update(); input.focus();
    return response;
  }
  function openFeedback(target = null) {
    if (!state.session) return;
    window.GraphMineShell.setPanel("data", false);
    feedbackTarget = target;
    $("conversation-feedback-form").reset();
    $("conversation-feedback-dialog").querySelector(".dialog-notice")?.remove();
    $("conversation-feedback-target").textContent = target?.turn_id ? "Your feedback will be saved with this answer and its conversation." : "Your feedback will be saved with the latest answer and its conversation.";
    fields(); $("conversation-feedback-dialog").showModal(); $("conversation-feedback-note").focus();
  }
  function fields() {
    const category = $("conversation-feedback-kind").value;
    $("conversation-feedback-expected").required = category === "correction";
    $("conversation-feedback-rating").required = category === "rating";
    $("conversation-feedback-note").required = !["rating", "correction"].includes(category);
  }
  function decorate(item, row) {
    const local = row.kind?.startsWith("feedback_command");
    if (local) item.article.classList.add("local-command");
    if (row.role !== "assistant") return;
    if (row.command === "export" && state.session) {
      const button = node("button", {type: "button", class: "quiet command-download"}, "Download session archive");
      button.addEventListener("click", () => runAction(() => download(`/api/sessions/${state.session.id}/history/archive`, `${state.session.id}.zip`)));
      item.bubble.append(button);
    } else if (!local && (row.turn_id || row.result_id || row.job_id)) {
      const button = node("button", {type: "button", class: "quiet answer-feedback"}, "Give feedback");
      button.addEventListener("click", () => openFeedback({turn_id: row.turn_id || null, result_id: row.result_id || null, job_id: row.job_id || null}));
      item.bubble.append(button);
    }
  }
  $("conversation-help").addEventListener("click", () => { window.GraphMineShell.setPanel("data", false); runAction(() => send("/help")); });
  $("conversation-feedback").addEventListener("click", () => openFeedback());
  $("conversation-feedback-kind").addEventListener("change", fields);
  $("close-conversation-feedback").addEventListener("click", () => $("conversation-feedback-dialog").close());
  $("conversation-export").addEventListener("click", () => runAction(() => download(`/api/sessions/${state.session.id}/history/archive`, `${state.session.id}.zip`)));
  $("conversation-export-feedback").addEventListener("click", () => runAction(() => download(`/api/sessions/${state.session.id}/feedback/export`, `${state.session.id}-feedback.jsonl`)));
  $("conversation-feedback-form").addEventListener("submit", event => {
    event.preventDefault(); runAction(async () => {
      await ensureSession();
      const category = $("conversation-feedback-kind").value;
      const expected = $("conversation-feedback-expected").value.trim() || null;
      const rating = $("conversation-feedback-rating").value ? Number($("conversation-feedback-rating").value) : null;
      const note = $("conversation-feedback-note").value.trim() || (category === "rating" ? `User rated this answer ${rating}/5` : "User supplied a corrected answer");
      await api(`/api/sessions/${state.session.id}/feedback`, {method: "POST", body: W.stringify({...feedbackTarget, category, what_went_wrong: note, expected_behavior: expected, rating})});
      state.feedbackCount = (state.feedbackCount || 0) + 1;
      $("conversation-feedback-dialog").close(); update(); notice("Feedback saved with the conversation. No model call was made.");
    });
  });
  return {isCommand, send, decorate, update, close};
};
