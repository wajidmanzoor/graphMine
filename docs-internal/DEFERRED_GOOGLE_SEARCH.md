# Deferred Google search

Status: disabled for the current release, at the user's request on 2026-11-17.
The completed graph-analysis, clarification, options, grounding, and citation
features can be promoted independently of web retrieval.

## Current behavior

`GRAPHMINE_GOOGLE_SEARCH_ENABLED` defaults to `false`. Normal deployments keep it
false. Explicit web-search requests receive “Web search is currently disabled.”
The search function returns before opening an HTTP connection or browser, and
the answer has no Google search link or invented web sources. Local graph facts,
saved-result explanations, and documentation-backed conceptual answers continue
to work.

The prototype remains in `agent/graphmine_agent/google_search.py`; routing is in
`analytics_planning.py`. Its parser and enabled-mode tests are retained. An
explicit development opt-in can use `GRAPHMINE_GOOGLE_SEARCH_ENABLED=true`.
That opt-in does not make ordinary Google requests reliable.

## Why it was deferred

The deployment can reach Google over HTTPS. Direct search requests returned a
JavaScript page without usable results; the browser fallback encountered Google's
bot protection. No outbound application proxy or Tailscale exit node was found.
Cloudflare Tunnel publishes the application but does not change the server's
ordinary outbound search connection. No network settings were changed.

The prototype extracts short search-result snippets, not full destination pages.
Successful parsing is covered by fixtures; successful live retrieval was not
established. Google documents its unusual-traffic behavior at
<https://support.google.com/websearch/answer/86640?hl=en>.

## Later development

1. Select a retrieval provider. Serper (<https://serper.dev/>) was suggested as a
   third-party Google-results API compatible with keeping Qwen as the agent's
   model. No provider account, key, paid plan, or integration has been created.
   Google's Gemini search grounding is a separate option that also involves a
   Gemini model call. The older Custom Search JSON API is closed to new customers;
   check current provider documentation before implementing an alternative.
2. Store any provider key in private deployment configuration. Send only the
   approved public search query, never uploaded graph records or hidden history.
3. Preserve the current-turn source registry, exact references, citation checks,
   and prohibition on web-backed graph-data answers. Fetch destination-page text
   separately when needed and accessible, distinguishing it from result snippets.
4. Add caching, usage limits, timeouts, and explicit unavailable responses. Keep
   bot checks terminal; do not add CAPTCHA solving or proxy rotation.
5. Test disabled-mode network isolation, provider success/errors, citation safety,
   UI behavior, and a live request from the intended deployment network. Enable
   production only as part of a separately validated release.

Provider references:

- <https://serper.dev/>
- <https://ai.google.dev/gemini-api/docs/google-search>
- <https://developers.google.com/custom-search/v1/overview>
