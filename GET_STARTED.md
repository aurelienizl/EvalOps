# Get started

Run commands from the repository root. You need Linux, Docker Engine and Docker
Compose. The container manager needs access to the local Docker socket.

## 1. Configure

```sh
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_hex(32))'
```

Edit `.env`:

- Set `POSTGRES_PASSWORD`, `BACKEND_DB_PASSWORD` and `MANAGER_DB_PASSWORD` to three
  different values. Run the generation command once for each password; hexadecimal
  values work directly in the PostgreSQL connection URLs.
- Set `DATA_ROOT` to an absolute host path (default `/var/lib/evalops`). Compose
  mounts it at the same path inside the manager.
- Set `SSH_HOST` to the hostname or IP reachable by students. `localhost` works
  for local use. SSH ports default to 20000–30000; allow access to these ports.
- Set `COOKIE_SECURE=true` when serving HTTPS through an external proxy. Keep it
  `false` for local HTTP. The proxy should forward to `127.0.0.1:8080`.

Other defaults are in [compose.yaml](compose.yaml), including the environment
limit (`MAX_ENVIRONMENTS=20`), lifetime (`ENVIRONMENT_TTL_SECONDS=43200`, 12 hours) and manager
polling interval (`POLL_INTERVAL_SECONDS=1`).

## 2. Start

```sh
docker compose up --build -d
docker compose ps
docker compose logs -f container_manager
```

On first startup, PostgreSQL initializes the schema and database roles. The manager
loads courses and builds exercise images before the backend becomes available;
this can take several minutes. Initialization scripts run only on a new database
volume. Existing databases must already have the schema and roles defined in
[db/](db/); changing `.env` passwords does not update existing database roles.

Open the [application](http://localhost:8080) or [API documentation](http://localhost:8080/docs).
There are no default accounts.

## 3. Create accounts

```sh
docker compose exec backend python -m backend.src.cli admin@example.org --role admin
docker compose exec backend python -m backend.src.cli student@example.org
```

Enter a password of at least 12 characters at the prompt. Running a command again
resets that account's password and role and revokes its sessions. Account
management stays in the CLI.

## 4. Try an exercise

1. Sign in and save your public SSH key under **Profile**.
2. Open a course and exercise, then start its environment.
3. Connect with the displayed SSH command and work in the exercise directory.
4. Select **Evaluate**. The manager stops development before grading, saves a
   workspace snapshot, then publishes the report and unlocks controls.

Only one development container is allowed per student. Stop it before switching
exercises. Evaluation requires that exercise's environment to be running; restart
it before another submission. Files persist after stop and grading.

The SSH command skips host identity checks with `StrictHostKeyChecking=no` and
`UserKnownHostsFile=/dev/null` because disposable containers reuse SSH ports.

## Updates and storage

- After code changes: `docker compose up --build -d`.
- After course-only changes: `docker compose restart container_manager`.

Courses live in `courses/<course>/course.yaml`. Each exercise has an `exercise.yaml`,
a student-facing `README.md`, and `dev/` and `evaluator/` images. Use
[courses/examples/](courses/examples/) as a template. Exercise IDs and workspace
directory names must be unique. Removing a course folder does not delete its
historical database records.

PostgreSQL data lives in the Compose `database` volume. `DATA_ROOT` contains
`workspaces/`, manager-owned SSH `keys/` and grading `snapshots/`. Back up both the
volume and `DATA_ROOT`; archives are retained until an operator removes them.
The backend mounts snapshots read-only and has no Docker access.

Inspect services with `docker compose logs -f backend container_manager`. Stop
student environments before stopping the application services with
`docker compose stop`. Do not use `docker compose down -v` to preserve your database.

## Local development and checks

With the backend/Compose stack running, Node 22+ can serve frontend edits without
installing dependencies:

```sh
node frontend/server.mjs
```

Open `http://127.0.0.1:3000`. Optional `PORT` and `API_UPSTREAM` environment variables
change the development server's port and API destination (default
`http://127.0.0.1:8080`). Check sign-in, start/stop, grading, profile and admin in
the browser.

For backend and container-manager checks, install the Python test dependencies:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check backend/src container_manager/src tests
.venv/bin/pytest -q -s
```

**The tests reset this deployment:** they stop its services, delete the database
volume and clear managed workspaces, SSH keys and snapshots before running. They
use the current `.env` and Compose file, then clean up again afterward. The suite
includes five students working concurrently through SSH; the frontend is not run.
See [tests/README.md](tests/README.md) for requirements, groups and coverage.
