# Container manager

The manager runs on the internal `backend_manager` network and listens on port `8001`. It owns Docker operations. The backend handles user authorization and persistent scores; the manager handles container state, image availability and per-student serialization.

See [ARCHITECTURE.md](ARCHITECTURE.md) for startup ordering and the supported deployment model.

## Code layout

| Module | Responsibility |
| --- | --- |
| `src/app.py` | Synchronous startup, client cleanup, error handlers, router assembly |
| `src/services/state.py` | One copy of process-local state and readiness guards |
| `src/builds.py` | Sequential development/evaluator image builds and their report |
| `src/docker_runtime.py` | Docker resources, SSH keys, ports, operations, evaluation and snapshots |
| `src/api/v1/` | Thin HTTP adapters for system, environment, evaluation and operation endpoints |
| `shared/contracts.py` | Requests and responses shared with the backend |

## Startup and health

Startup validates the catalog and SSH port range, checks Docker connectivity, removes lingering containers belonging to `PLATFORM_INSTANCE`, and builds both images for each exercise. Builds finish before the application accepts HTTP requests. An initialization failure aborts startup.

`GET /v1/health` returns `200` only when startup is ready. It returns `status`, `instance_id`, `phase`, and `error`. Docker health checks fail while the listener is unavailable during builds. Compose allows `CONTAINER_MANAGER_START_PERIOD` (default `30m`) before counting those failures.

`GET /v1/catalog` returns `catalog_hash`, `available`, `phase`, and `build_report`. Each exercise report contains `available`, image IDs/tags, and an optional error. A failed exercise stays unavailable; other successful exercises remain usable after the build pass.

## HTTP interface

All errors use `{"error": {"code": "...", "message": "..."}}`; mutation errors include the operation ID when available. Request identifiers allow letters, numbers, underscores and hyphens, and reject path traversal.

| Method | Route under `/v1` | Behavior |
| --- | --- | --- |
| GET | `/health` | Manager health |
| GET | `/catalog` | Catalog fingerprint and build availability |
| GET | `/students/{student_id}/environment` | Live Docker state plus the current/last operation |
| POST | `/students/{student_id}/start` | Launch an exercise environment |
| POST | `/students/{student_id}/stop` | Remove student containers; retain workspace volume |
| POST | `/students/{student_id}/grade` | Stop containers, snapshot the exercise, evaluate and collect results |
| GET | `/students/{student_id}/operations/{operation_id}` | Read operation status/result |
| POST | `/students/{student_id}/ssh-key` | Write the requested public key into the workspace |
| GET | `/students/{student_id}/evaluations/{operation_id}/snapshot` | Stream the gzip snapshot |

Start requires `operation_id`, `exercise_id`, and `ssh_public_key`. Stop requires `operation_id`. Grade requires `operation_id` and `exercise_id`. SSH-key updates require `public_key`.

An environment inspection returns:

```json
{
  "state": "running",
  "exercise_id": "hello-c",
  "ssh": {"host": "localhost", "port": 22000, "user": "student"},
  "active_operation": null
}
```

A grade result returns `operation_id`, `exercise_id`, `status`, evaluator `tests`, optional `stdout`/`stderr`, and optional `error_code`/`error_message`. The backend computes percentages from the validated test list and persists completion. An evaluator writes `{"schema_version": 1, "tests": [...]}` to `/result/result.json`, with a boolean `passed` for each uniquely identified test.

## Docker resources

| Resource | Name |
| --- | --- |
| Development container | `devops-{platform_instance}-dev-{student_id}` |
| Evaluator container | `devops-{platform_instance}-eval-{student_id}-{operation_id}` |
| Persistent workspace | `devops-{platform_instance}-student-{student_id}` |

Both startup and per-student container cleanup filter by platform instance.

Each student container has a CPU limit of `0.5`, a memory limit of `512m`, and a PID limit of `96`. Evaluators have no network and mount the student volume read-only; their result directory is writable. Development images define the student tools, SSH service, and writable root filesystem.

SSH ports are allocated sequentially within the configured range while checking Docker port bindings. A failed start removes any partially created container and releases its reservation after cleanup. Docker inspection failures propagate instead of being interpreted as an empty list of containers.

## Evaluation and files

The student lock covers container removal, snapshot creation and evaluator execution. Container-removal failures abort evaluation. Evaluator timeouts, nonzero exit codes, malformed JSON and invalid result schemas produce explicit errors. The evaluator and temporary result directory are cleaned up on every exit path.

Keys are written through directory descriptors and atomic replacement, so student-created symlinks/hard links cannot redirect a privileged key write. Snapshots are stored in `/data/snapshots/{student_id}/{operation_id}.tar.gz` on the persistent `manager_data` volume, outside student homes. Snapshot downloads open the archive without following links and stream that open file, preventing path changes from redirecting the response. Back up `manager_data` alongside the database and student volumes.

The manager stores only the current/last operation per student in memory. This is sufficient for timeout reconciliation while the manager is running. The backend records a pending evaluation as interrupted when a manager restart has removed its operation history.
