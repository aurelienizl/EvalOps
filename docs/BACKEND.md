# EvalOps Backend Architecture & API Reference

The **Backend** (`backend`) is the core business application of the EvalOps platform. It manages user accounts, authenticates sessions via secure cookies, enforces role-based access control (students and administrators), parses the course catalog, handles SQLite persistence with WAL mode, serializes mutating operations via per-student locks, enforces evaluation quotas, and orchestrates calls to the Container Manager via a dedicated service client.

> **Network Position**: The Backend is accessible on the `frontend_backend` network (port `8000`) and communicates with the `container_manager` on the internal `backend_manager` network (port `8001`).

---

## 1. Component Architecture

```
backend/
├── Dockerfile                  # Backend container build definition
└── src/                        # Python application
    ├── __init__.py
    ├── app.py                  # Streamlined FastAPI application entrypoint & lifespan
    ├── state.py                # Shared platform runtime state & catalog singletons
    ├── schema.sql              # Relational SQLite database schema with role support
    ├── cli.py                  # Administrative CLI (create-user, set-role, list-users, init-db)
    ├── db.py                   # SQLite access layer (WAL mode, transactions, query repositories)
    ├── runtime.py              # RuntimeManager: per-student locks & container orchestration
    ├── core/
    │   ├── __init__.py
    │   ├── security.py         # Argon2id password hashing & Ed25519 key validation
    │   └── dependencies.py     # FastAPI dependencies (auth, csrf, require_admin, roles)
    ├── services/
    │   ├── __init__.py
    │   └── container_client.py # Dedicated typed HTTP client to Container Manager
    └── api/
        ├── __init__.py
        └── v1/                 # Modular API routers
            ├── __init__.py     # Aggregator router mounting /api/v1/*
            ├── auth.py         # Authentication (login, logout, me)
            ├── profile.py      # Profile management (password, ssh-key)
            ├── courses.py      # Catalog & exercises endpoints
            ├── evaluations.py  # Grading history & code snapshots
            ├── environment.py  # Student container control (start, stop, grade)
            ├── admin.py        # Generic admin query interfaces (users, evals, stats, locks)
            └── system.py       # Health checks and platform readiness (/health, /ready)
```

| Module / Package | Primary Responsibility |
|---|---|
| **[`app.py`](../backend/src/app.py)** | FastAPI bootstrap, unified error exception handlers, and router inclusion. |
| **[`api/v1/`](../backend/src/api/v1/)** | Student and administrator route handlers. |
| **[`core/`](../backend/src/core/)** | Password hashing (`Argon2id`), session token generation, Ed25519 validation, and permission dependencies (`require_admin`). |
| **[`services/container_client.py`](../backend/src/services/container_client.py)** | HTTP client for communication with `container_manager`. |
| **[`db.py`](../backend/src/db.py)** | SQLite connection manager with WAL mode, initial schema creation, and query functions with pagination. |
| **[`cli.py`](../backend/src/cli.py)** | Command-line management tool for user creation, role assignment, and database administration. |

---

## 2. Database Model & Persistence (SQLite WAL)

The application uses SQLite with Write-Ahead Logging (`PRAGMA journal_mode = WAL`) and foreign key constraints (`PRAGMA foreign_keys = ON`).

```
┌──────────────┐       1:N       ┌──────────────┐
│   students   │ ───────────────< │   sessions   │
│(users+roles) │                 └──────────────┘
└──────────────┘                 
       │ 1:1                             
       ├───────────────────────< ┌─────────────────┐
       │ 1:N                     │ student_runtime │
       ├───────────────────────< └─────────────────┘
       │                         ┌───────────────┐
       │ 1:N                     │  evaluations  │
       └───────────────────────< └───────────────┘
                                         ▲
                                         │ 1:1 (successful_evaluation_id)
                                 ┌───────────────────┐
                                 │ student_exercises │
                                 └───────────────────┘
```

### Table Definitions

| Table | Primary Key | Description |
|---|---|---|
| **`students`** | `id` (UUID) | User profile: `email` (unique), `password_hash`, `role` (`'student'` or `'admin'`), `ssh_public_key`, `created_at`. |
| **`sessions`** | `token_hash` (SHA-256) | Active web sessions: `student_id` (FK cascade), `csrf_token`, `expires_at`. |
| **`student_runtime`** | `student_id` (FK) | In-flight operation lock state: `operation_id`, `operation_type`, `started_at`, `phase`. |
| **`evaluations`** | `id` (UUID) | Historical grading records: `student_id`, `exercise_id`, `passed`, `total`, `percentage`, `tests_json`. |
| **`student_exercises`** | `(student_id, exercise_id)` | Permanent completion tracking: `completed_at`, `successful_evaluation_id` (FK evaluations). |

---

## 3. Security, Roles & Concurrency Mechanics

### 3.1 Authentication & CSRF
- **Session Cookie**: `session_token` cookie set with `HttpOnly`, `SameSite=Lax`, and `Path=/`.
- **Database Hashing**: The raw cookie token is hashed with SHA-256 before lookup in the `sessions` table.
- **CSRF Protection**: All mutating HTTP requests (`POST`, `PUT`, `DELETE`) require the `X-CSRF-Token` header matching the active session's token. Returns `403 CSRF_INVALID` on mismatch.
- **SSH Key Validation**: Only raw OpenSSH Ed25519 keys (`ssh-ed25519 AAAAC3...`) are accepted. RSA, DSA, ECDSA, comments, and multi-line keys are rejected with `422 INVALID_SSH_KEY`.

### 3.2 Role-Based Access Control (RBAC)
- **Roles**: Users have a `role` field: either `'student'` or `'admin'`.
- **Admin Endpoints**: Protected via FastAPI dependency `require_admin` (or `require_admin_csrf` for mutating calls). Unauthorized attempts return `403 FORBIDDEN`.

### 3.3 Per-Student Concurrency Locking
Mutating actions on an environment (`/start`, `/stop`, `/grade`) acquire a per-student lock in memory (`RuntimeManager.get_student_lock(student_id)`):
- If Student A is running an operation and sends another request, the second request fails immediately with `409 OPERATION_IN_PROGRESS`.
- **Student Isolation**: Locks are strictly keyed by `student_id`. Concurrent requests from different students run in parallel without blocking each other.
- **Admin Unlock**: Administrators can reconcile a stuck operation using `/api/v1/admin/environments/{student_id}/unlock`. The backend refuses while a local worker or manager operation is still running.

### 3.4 Evaluation Rate Limiting & Quotas
Each exercise manifest specifies `max_evaluations` (default: 3) within an `evaluation_window_minutes` window (default: 60 min).
- The backend counts submitted evaluations in the database within the sliding window, including failed or interrupted attempts.
- When exhausted, requests return `429 EVALUATION_RATE_LIMITED` with a `Retry-After: <seconds>` HTTP header.

---

## 4. REST API Endpoints Reference

All endpoints return JSON responses. Errors follow the standard format: `{"error": {"code": "...", "message": "..."}}`.

### 4.1 Authentication & Profile

| Method | Endpoint | Description | Auth Required | CSRF Required |
|---|---|---|:---:|:---:|
| `POST` | `/api/v1/auth/login` | Authenticates with `email` and `password`. Sets session cookie. | No | No |
| `POST` | `/api/v1/auth/logout` | Revokes the active session cookie. | Yes | Yes |
| `GET` | `/api/v1/auth/me` | Returns current user info (`id`, `email`, `role`, `csrf_token`). | Yes | No |
| `GET` | `/api/v1/profile` | Returns current user profile (`email`, `role`, `ssh_public_key`). | Yes | No |
| `PUT` | `/api/v1/profile/password` | Changes user password and revokes all active sessions. | Yes | Yes |
| `PUT` | `/api/v1/profile/ssh-key` | Validates Ed25519 key, saves in DB, and syncs to container manager. | Yes | Yes |

---

### 4.2 Courses & Catalog

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/courses` | Lists all published courses with student progress statistics. |
| `GET` | `/api/v1/courses/{course_id}` | Returns course details, deadline, and contained exercises. |
| `GET` | `/api/v1/exercises/{exercise_id}` | Returns exercise details, difficulty, completion status, and remaining quota. |
| `GET` | `/api/v1/exercises/{exercise_id}/resources/{resource_id}` | Downloads course resource file. |

---

### 4.3 Environment Control

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/environment` | Queries live environment status, SSH host/port, and locking state. |
| `POST` | `/api/v1/exercises/{exercise_id}/start` | Starts dev container for the exercise and injects student's SSH key. |
| `POST` | `/api/v1/environment/stop` | Stops the running dev container. |
| `POST` | `/api/v1/exercises/{exercise_id}/grade` | Initiates grading, records score in DB, updates completion. |

---

### 4.4 Evaluations & History

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/exercises/{exercise_id}/evaluations` | Returns student's evaluation history for this specific exercise. |
| `GET` | `/api/v1/evaluations/{evaluation_id}` | Detailed results for a specific evaluation, including test list. |
| `GET` | `/api/v1/evaluations/{evaluation_id}/snapshot` | Downloads `.tar.gz` archive of student code at evaluation time. |

---

### 4.5 Admin & Generic Query Interfaces (Admin Only)

| Method | Endpoint | Description | Query Parameters |
|---|---|---|---|
| `GET` | `/api/v1/admin/users` | Lists users with search and role filtering | `search`, `role`, `limit`, `offset` |
| `POST` | `/api/v1/admin/users` | Creates a new user with specific role | Payload: `{ email, password, role }` |
| `PUT` | `/api/v1/admin/users/{user_id}/role` | Updates user permission role (`student` / `admin`) | Payload: `{ role }` |
| `GET` | `/api/v1/admin/evaluations` | Global evaluation log across all students | `student_id`, `exercise_id`, `status`, `limit`, `offset` |
| `GET` | `/api/v1/admin/environments` | Lists all in-flight student operations and active locks | None |
| `POST` | `/api/v1/admin/environments/{student_id}/unlock` | Clear a stale operation after confirming that no local worker or manager operation is active | None |
| `GET` | `/api/v1/admin/stats` | Aggregated platform metrics (users, evals, completion) | None |

---

### 4.6 System & Health

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Fast liveness probe. |
| `GET` | `/api/v1/ready` | Readiness check (validates catalog fingerprint match with Container Manager). |

---

## 5. Administration CLI (`backend.src.cli`)

Administrative commands can be executed directly inside the backend container or during local development:

```bash
# In production via Docker Compose:
docker compose exec backend python -m backend.src.cli --help

# 1. Create a user account (default role: student):
docker compose exec backend python -m backend.src.cli create-user --email etudiant@ecole.fr

# 2. Create an administrator account:
docker compose exec backend python -m backend.src.cli create-user --email prof@ecole.fr --role admin

# 3. List existing user accounts:
docker compose exec backend python -m backend.src.cli list-users --role admin

# 4. Modify an existing account's role:
docker compose exec backend python -m backend.src.cli set-role --email etudiant@ecole.fr --role admin

# 5. Reset a user's password (instantly revokes all active sessions):
docker compose exec backend python -m backend.src.cli reset-password --email etudiant@ecole.fr

# 6. Initialize SQLite schema:
docker compose exec backend python -m backend.src.cli init-db
```
