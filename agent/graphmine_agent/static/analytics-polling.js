/* Conversation and workflow observation; mutations remain explicit actions. */
"use strict";
window.GraphMinePolling = ({state, readScope, getSignal, syncConversation, renderWorkflow, renderConversation, loadSaved, loadResults, showWorkflowSync, go, notice}) => {
  let workflowPollGeneration = 0, workflowUpdatesPending = false;
  const POLL_FAST = 1400, POLL_IDLE = 10000;
  function pollConversation(delay = POLL_FAST) {
    clearTimeout(state.eventPoll); const epoch = state.epoch;
    state.eventPoll = setTimeout(async () => {
      // Slow down while nothing changes; hidden tabs wait until they are shown again.
      let next = Math.min(Math.max(delay, POLL_FAST) * 1.5, POLL_IDLE);
      if (!document.hidden) {
        try { if (await syncConversation() || state.planning) next = state.eventBacklog ? 0 : POLL_FAST; }
        catch (error) { if (error.status === 401) return; /* Signed out: the login dialog takes over and reloads. */ }
      }
      if (epoch === state.epoch && state.session) pollConversation(next);
    }, delay);
  }
  function resumeUpdates() {
    if (document.hidden) return;
    if (state.session) pollConversation(0);
    if (workflowUpdatesPending) pollWorkflow(0);
  }
  document.addEventListener("visibilitychange", resumeUpdates);
  window.addEventListener("online", resumeUpdates);
  function pollWorkflow(delay = 600, failures = 0) {
    clearTimeout(state.poll);
    workflowUpdatesPending = true;
    const generation = ++workflowPollGeneration;
    const id = state.record?.id, reads = readScope(getSignal());
    const current = () => generation === workflowPollGeneration && reads.current() && state.record?.id === id;
    state.poll = setTimeout(async () => {
      if (!current()) return;
      if (document.hidden || !navigator.onLine) {
        showWorkflowSync(document.hidden ? "Analysis updates are paused while this tab is in the background." : "You are offline. Analysis updates will resume when you reconnect.");
        return;
      }
      try {
        const record = await reads.get(`/api/workflows/${id}`);
        if (!current()) return;
        state.record = record; renderWorkflow(); renderConversation();
        if (["queued", "running"].includes(record.status)) { showWorkflowSync(""); pollWorkflow(); }
        else {
          await loadSaved();
          if (!current()) return;
          await loadResults();
          if (!current()) return;
          workflowUpdatesPending = false; showWorkflowSync("");
          if (record.status === "completed" && state.files.find(f => f.id === state.active)?.provenance?.source?.database_source) go("results", record.id);
          notice(record.status === "completed" ? "The computed results are ready." : record.error?.message || `Execution ${record.status}. Inspect the step status for details.`, record.status === "failed");
        }
      } catch (error) {
        if (!current() || error.name === "AbortError") return;
        if ([401, 403, 404].includes(error.status)) {
          workflowUpdatesPending = false;
          showWorkflowSync(error.status === 401 ? "Sign in again to receive analysis updates." : "This analysis is no longer accessible. Open a saved conversation to continue.");
          return;
        }
        const retryDelay = window.GraphMineAsync.backoff(failures, error.retryAfter || 0);
        showWorkflowSync(`Analysis updates are temporarily unavailable. Retrying in ${Math.ceil(retryDelay / 1000)} seconds. Your analysis may still be running.`, true);
        pollWorkflow(retryDelay, failures + 1);
      }
    }, delay);
  }
  function resetWorkflow() {
    clearTimeout(state.poll); workflowPollGeneration++; workflowUpdatesPending = false; showWorkflowSync("");
  }
  return {pollConversation, pollWorkflow, resetWorkflow};
};
