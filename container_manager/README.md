# Container manager

A Python process that loads the course catalog and manages development and grading
containers through the Docker SDK. Run **one instance per Docker host**.

## Execution

At startup, the manager validates `courses/`, builds missing exercise images,
publishes the catalog to PostgreSQL and reconciles existing containers.

It then uses **one database connection and one sequential action loop**:

1. Read pending requests and reconcile container state.
2. Finish each start, stop or grading action before taking the next one.
3. Wait for PostgreSQL notifications or the polling interval, then repeat.

Database rows retain queued work; notifications only wake the loop sooner.
A database advisory lock rejects a second manager connected to the same database.
Grading also queues other students' start/stop requests until the action finishes.

## Actions

- **Start:** prepare the saved workspace and SSH key, launch a development
  container, wait for SSH readiness, then record its container ID and port.
- **Stop:** remove the development container, confirm removal, then release its
  state. Student files remain on disk.
- **Grade:** the backend first requires the exercise's environment to be running
  and reserves it as `grading`. The manager stops all development containers for
  that student, archives the workspace, runs the evaluator with limits, collects
  results and removes the evaluator before unlocking. Development stays stopped.

State updates check operation IDs to avoid overwriting newer requests. Recovery
retries uncertain cleanup, expires environments and handles interrupted grading.
Unconfirmed cleanup keeps controls locked. Evaluators have no network, and student
programs run separately from the trusted grader's results directory.

## Code layout

| Path | Role |
| --- | --- |
| `src/main.py` | Startup, action loop and shutdown |
| `src/catalog/` | Manifest validation, image builds and catalog publication |
| `src/runtime/` | Docker, workspaces, SSH material and recovery |
| `src/grading/` | Evaluation execution, result parsing and trusted runner |
| `src/database/` | Connection, notifications and SQL state transitions |
| `src/core/` | Settings and internal health probes (`/ready`, port 8001) |

Setup, storage and commands: [Get started](../GET_STARTED.md).
