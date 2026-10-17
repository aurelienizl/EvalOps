# Frontend

A static HTML/CSS/JavaScript console served by Nginx. Three application modules
handle the UI; there is no framework, build step or npm installation required.
Nginx forwards API requests to the backend on the same origin, using its session
cookie for authentication.

## Screens and behavior

- Course cards, exercise subjects, resources and evaluation history.
- A shared runtime banner with the SSH command and environment controls.
- Evaluation reports, output differences and submitted-workspace downloads.
- Profile forms for SSH keys and passwords.
- Admin metrics, active operations and filtered evaluation logs. Account
  creation and role changes stay in the backend CLI.

Hash routes select screens. One loop polls environment state every two seconds
and refreshes exercise/admin data every ten seconds. Unknown state and active
operations lock controls. Evaluate requires the current exercise's environment
to be running, an open deadline and available quota; the backend enforces admission.

API values are escaped, Markdown uses local Marked/DOMPurify copies, and test
output is displayed as text. Admin elapsed times include waiting and cleanup;
state-update timestamps do not measure SSH activity.

## Code layout

| Path | Role |
| --- | --- |
| `public/index.html`, `public/styles.css` | Shared shell and responsive dark layout |
| `public/js/app.js` | Navigation, forms, actions and refresh loop |
| `public/js/views.js` | Screen templates and Markdown rendering |
| `public/js/api.js` | Requests and HTML formatting helpers |
| `public/vendor/` | Marked and DOMPurify, with licenses |
| `nginx.conf`, `Dockerfile` | Production static server and API proxy |
| `server.mjs` | Optional local server and API proxy |

Setup and local development: [Get started](../GET_STARTED.md).
