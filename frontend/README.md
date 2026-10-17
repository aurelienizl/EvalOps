# Frontend

A static HTML/CSS/JavaScript console served by Nginx. Small application modules
handle the UI; there is no framework, build step or npm installation required.
Nginx forwards API requests to the backend on the same origin, using its session
cookie for authentication.

The production proxy caps API traffic at 100 requests/second for the whole app,
with an immediate burst allowance of 100 excess requests. Login and password
changes share a stricter cap of two requests/second, queuing up to 20 excess
requests (about ten seconds). Excess traffic receives HTTP 429 with a JSON
message and `Retry-After: 1`. Backend quota responses keep their own retry headers.
Static assets, documentation and health checks do not consume these allowances.

These limits are shared by all students, including clients behind Nginx Proxy
Manager. Forwarded IP headers are not trusted by default. Per-client throttling
requires configuring the frontend to trust only the actual proxy address and
adding limits keyed by the restored client address; per-account login protection
belongs in the backend. Tune the shared caps for your class size and server.
After editing `nginx.conf`, rebuild with `docker compose up -d --build frontend`.

## Screens and behavior

- Course cards, exercise subjects, resources and evaluation history.
- A shared runtime banner with the SSH command and environment controls.
- Evaluation reports, output differences and submitted-workspace downloads.
- Profile forms for SSH keys and passwords.
- A teacher dashboard with paginated email search, student progress and students
  who have not submitted yet. Course filters scope progress; accounts are not
  organized into enrollment groups.
- Student detail panels with persistent validation counts, submission history,
  full evaluation reports, and current workspace status.
- Separate submissions and workspaces views, with clear distinctions between
  unsuccessful submissions, timeouts and system errors. Account creation and
  role changes stay in the backend CLI.

Hash routes select screens. One loop polls environment state every two seconds
and refreshes exercise/admin data every ten seconds. Unknown state and active
operations lock controls. Evaluate requires the current exercise's environment
to be running, an open deadline and available quota; the backend enforces admission.

API values are escaped, Markdown uses local Marked/DOMPurify copies, and test
output is displayed as text. Admin elapsed times include waiting and cleanup;
state-update timestamps do not measure SSH activity. Platform metric cards cover
all courses; the roster, submission history and workspace list follow their course
and email filters. Background refresh preserves draft filters, panel selection,
focus and table scroll. The backend pages and aggregates existing records rather
than downloading all student history into the browser.

## Code layout

| Path | Role |
| --- | --- |
| `public/index.html`, `public/styles.css` | Shared shell and responsive dark layout |
| `public/js/app.js` | Navigation, forms, actions and refresh loop |
| `public/js/views.js` | Screen templates and Markdown rendering |
| `public/js/api.js` | Requests and HTML formatting helpers |
| `public/js/admin.js`, `public/admin.css` | Teacher views, student panel and refresh behavior |
| `public/js/admin-data.js` | Result labels, URL filters and progress rules |
| `public/vendor/` | Marked and DOMPurify, with licenses |
| `nginx.conf`, `Dockerfile` | Production static server and API proxy |
| `server.mjs` | Optional local server and API proxy |

Setup and local development: [Get started](../GET_STARTED.md).

## Checks

Run the dependency-free JavaScript checks with `npm test --prefix frontend`.
For real Chromium tests against the backend and frontend proxy:

```sh
.venv/bin/pip install -r tests/frontend/requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/pytest -q -s tests/frontend
```

The browser tests use the same deployment-reset fixture as the other integration
tests. Read [the test setup and reset behavior](../tests/README.md) first.
