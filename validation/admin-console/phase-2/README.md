# Admin console · phase 2 evidence

Chromium screenshots use a disposable account database. Account/event counts come
from API writes, hardware figures come from server probes, and unconfigured
services show their availability reason. No example production numbers are seeded.

| Page | Implemented screen | Reference |
| --- | --- | --- |
| Overview | [Desktop](overview.png), [mobile](overview-mobile.png) | [Supplied design](https://claude.ai/artifact/UKFqcyexaJ5vSA8YkzWAeA#page-dcb81aee8d83) · unavailable behind verification |
| Health | [Desktop](health.png), [self-test dialog](selftest-dialog.png) | Same reference · comparison pending |
| Model | [Desktop](model.png) | Same reference · comparison pending |

The reference page returns a security-verification challenge, including in the
automated browser. These images demonstrate implementation and responsive behavior;
they do not establish exact artboard fidelity.

`test_admin_monitor_browser.py` opens every phase-2 page, saves idle/thinking
settings through the API, checks the values after reload, and finds the corresponding
admin-change event. The API suite covers probe timeouts and cache reuse, incident
opening/recovery, range/type validation, restart confirmation, queue measurements,
and external rejection of self-test credentials and tokens. The self-test acceptance
uses real sign-in, graph upload, native CPU execution, and result retrieval, with an
authored question-provider response; it is not a claim of live LLM accuracy.

Production services and real user accounts are not changed by these tests.
