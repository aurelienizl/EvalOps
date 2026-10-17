# Tests

Real integration tests for the backend and container manager. Every test run
uses the repository's `compose.yaml` and current Compose environment (`.env` and
shell variables). The optional browser checks also start a temporary local
frontend proxy. All suites use the same Compose file and database.

**Development use only:** before running, the suite stops the current Compose
project, removes its database volume and managed containers/networks, and deletes
`DATA_ROOT/workspaces`, `keys` and `snapshots`. It repeats cleanup at the end.
Exercise sources and cached images are kept. Other deployments are not removed.

## Run

You need Linux, Docker Engine/Compose, Python 3.11+, OpenSSH (`ssh`, `ssh-keygen`),
a configured `.env` and the built-in `hello-c` / `sum-c` exercises. `SSH_HOST` must
be reachable from the test machine. The five-student scenario requires capacity
for at least five environments (`MAX_ENVIRONMENTS`, default 20).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q -s
```

Run one group with `pytest tests/backend`, `pytest tests/container_manager` or
`pytest tests/functional` from the same virtual environment. Each invocation
starts with the same full reset. Run suites sequentially against this deployment.

## Layout

| Directory | Checks |
| --- | --- |
| `backend/` | Real API authentication, catalog/resources, permissions, start/stop and grading races, quotas, deadlines, reports and admin cleanup |
| `container_manager/` | Running manager: catalog loading, instance guard, database requests, SSH, persistence, crash recovery, grading timeout and interrupted grading |
| `functional/` | Five concurrent students compile over SSH, submit passing/failing work, inspect snapshots, fix and resubmit, then complete a second exercise |
| `frontend/` | Optional Chromium checks for teacher search, progress, reports, refresh stability, mobile layout, workspace stopping and student access restrictions |
| `tools/` | Shared deployment reset, SQL requests, HTTP client, `SshClient`, user setup and bounded polling |

One session fixture starts PostgreSQL, the manager and backend with the existing
deployment settings. Tests use fresh accounts; users' environments are cleaned up
after each test. The API is reached through its Docker network address on Linux.
The HTTP helper sends the session cookie explicitly so tests can also exercise a
backend configured with `COOKIE_SECURE=true` without starting a TLS/frontend proxy.

Manager tests enqueue requests in PostgreSQL. Backend and functional tests submit
requests through HTTP. Actions finish in the real manager; tests do not call its
Python handlers or mock Docker. Small C examples are shared in `tools/users.py`.

## Browser checks

Install `tests/frontend/requirements.txt` and run
`.venv/bin/python -m playwright install chromium` to enable the Chromium tests.
Without Playwright, this group is skipped. Run `pytest tests/frontend` against a
development deployment with the same reset precautions described above.
The tests start a temporary local frontend proxy and authenticate with real API
sessions. Pure UI result/filter rules can also be checked without Docker using
`npm test --prefix frontend`.
