# Admin console — phase 1 evidence

Screenshots are produced by `agent/tests/test_admin_browser.py` against a disposable
local server. The account names and conversation shown are test fixtures; every
number in the screenshots is returned by that server. No production credentials or
conversation content are included.

The supplied reference is [GraphMine Admin Console](https://claude.ai/artifact/UKFqcyexaJ5vSA8YkzWAeA#page-dcb81aee8d83).
The reference returned a Cloudflare security-verification screen to Playwright.
Artboard matching and side-by-side comparison remain unverified until the design
can be opened or exported. These screenshots are implementation evidence only.

| Page or dialog | Screenshot |
| --- | --- |
| Users and shared shell | [Users](01-users.png) |
| Add user | [Add user](02-add-user.png) |
| Edit user | [Edit user](03-edit-user.png) |
| Delete user | [Delete user](04-delete-user.png) |
| Activity | [Activity](05-activity.png) |
| Before/after change details | [Admin change](06-admin-change.png) |
| Question metadata | [Question details](07-question-details.png) |
| Support access | [Grant dialog](08-support-access.png) |
| Read-only conversation | [Support view](09-support-read-only.png) |
| Narrow-screen shell | [Mobile Users](10-users-mobile.png) |
| Member and signed-out denial | [Access required](11-access-required.png) |

To reproduce, install the agent's test dependencies and Playwright Chromium, then:

```sh
PYTHONPATH=agent GRAPHMINE_ADMIN_SCREENSHOTS=validation/admin-console/phase-1 \
  python -m pytest agent/tests/test_admin_browser.py
```

The test creates its own accounts, SQLite store, Studio account file, and localhost
server. It does not access production accounts or invoke the model.
