# Service boundaries and operating model

EvalOps uses three services and synchronous HTTP requests. Each service has one responsibility:

| Service | Owns | Calls |
| --- | --- | --- |
| Frontend | Static HTML/JS, session display | Backend `/api/v1` |
| Backend | Authentication, authorization, catalog, scores and operation records in SQLite | Container manager `/v1` |
| Container manager | Docker images, containers, SSH ports, workspaces and snapshots | Docker Engine |

`shared/contracts.py` defines the manager request and response models. The backend validates manager responses before updating persistent records. Both APIs return errors as `{"error": {"code": "...", "message": "..."}}`. Transport failures and malformed responses remain errors; they must never appear as a stopped environment or successful operation.

Each service stores its process-local objects in one state module. The application lifespan initializes them, closes their clients, and clears them on shutdown. Routers use state accessors and do not import the application to find a second copy of those objects.

## Startup

1. The manager validates its configuration and catalog, connects to Docker, and removes lingering containers belonging to this platform instance.
2. It builds exercise images sequentially in the startup lifecycle. There is no background build thread; HTTP requests are accepted after the build pass finishes.
3. Manager health succeeds only after startup completes. Individual failed builds stay unavailable and are included in the build report; successful exercises can still be used.
4. Compose starts the backend after manager health succeeds. Backend readiness verifies that both services use the same catalog fingerprint.
5. Compose starts Nginx to serve frontend assets.

`CONTAINER_MANAGER_START_PERIOD` defaults to `30m`. It allows time for cold builds before Docker counts failing health checks. Successful health checks allow startup immediately; this is not a fixed delay. Increase it for a large catalog or a slow image registry.

The catalog fingerprint includes manifests, README files, exercise resources, and files in both Docker build contexts. Restart/recreate both Python services when catalog sources change.

## Student operations

The backend checks the user's role, exercise deadline, SSH key and evaluation quota. One operation can run per student, while different students can work concurrently. A persistent operation row records the operation ID; cleanup must remove only the row owned by that operation.

The manager is authoritative for Docker state and serializes student mutations. A failed container removal prevents evaluation from starting. An environment start writes the requested SSH key before launching the container. Snapshots live in the manager's persistent `/data/snapshots` directory, outside student workspaces. Snapshot and key access reject links that would redirect privileged filesystem operations.

Completed evaluation results are validated and persisted before returning scores. A transport timeout can leave work running in the manager; polling reconciles its terminal result rather than starting a second operation. A manual unlock must not release a lock owned by an active worker or discard a manager operation that is still running.

The browser treats unavailable exercises, expired deadlines, and active operations as disabled actions. Server checks remain authoritative. User/server values are rendered as text or escaped before inclusion in HTML.

## Capacity and deployment

The current deployment uses **one backend worker, one container manager worker, one Docker host, and SQLite**. Student operations are concurrent across students, but this is not a horizontally replicated deployment. Keep `--workers 1` for both services: process-local locks, Docker port reservations, and manager operation history depend on that operating model.

Increase CPU/RAM and the SSH port range as the number of concurrent environments grows. SQLite queries use indexes and bounded pagination, and quota checks fetch only the recent submissions they need. Each student container has CPU, memory, and PID limits. No broker, task queue, or additional database is required for this deployment.

Before adding replicas or multiple Docker hosts, deliberately move shared coordination and persistence to a common service and route a student to the correct manager. Adding replicas to the existing Compose configuration alone would not provide safe coordination.

## Verification

```bash
python -m pytest tests/unit
node --test tests/unit/frontend.test.mjs
docker compose config --quiet
docker compose up -d --build
python -m pytest tests/functional
```

Functional tests use a temporary backend database and test student identifiers. They need a healthy manager connected to Docker and the example courses.

The capacity simulation starts its own Compose backend and manager, with a fresh database and a temporary three-exercise catalog. It does not need the normal stack to be running. Enable it explicitly and choose the cohort size:

```bash
python -m pytest tests/functional/test_simulation.py --run-capacity --simulation-students=99 -q -s
```

The default cohort uses three groups of 33; other positive sizes are balanced across the three exercises. All environments start before grading begins, and each student retries only until success. Seeded outcomes give a 1/3 chance on the first submission, a conditional 1/2 chance on the second, and guaranteed success on the third. Reports record actual active environments, evaluation counts, throughput and request latencies. Cleanup removes only the simulation project's resources.
