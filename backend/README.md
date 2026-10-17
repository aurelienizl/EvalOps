# Backend

A Python API built with FastAPI and asyncpg. It handles authentication, course
access and student requests. PostgreSQL coordinates work with the container
manager; the backend never calls Docker or the manager directly.

## Responsibilities

- Authenticate student/admin accounts with session cookies and hashed passwords.
- Serve courses, exercise subjects, resources, evaluation reports and snapshots.
- Admit start, stop and grading requests in short transactions under a student lock.
- Enforce one development environment per student, deadlines and evaluation quotas.
- Provide admin metrics, operation monitoring and cleanup requests.

Grading requires a `running` environment for the requested exercise. Invalid
submissions return 409 without creating an evaluation or consuming quota.
Accepted operations return a polling URL; controls remain locked during transitions
and grading. Reports and snapshots are accessible only to their owner.

## Code layout

| Path | Role |
| --- | --- |
| `src/main.py` | Application startup, database pool and API routers |
| `src/api/` | Authentication, profile, catalog, environments, evaluations and admin routes |
| `src/core/` | Settings, password hashing and session authentication |
| `src/database/` | Pool and transaction helpers |
| `src/cli.py` | Create/reset accounts and set roles |

Routes use `/api/v1`. Interactive API documentation is served at `/docs`, and
`/healthz` checks database access. The backend runs behind the frontend's Nginx
proxy; an external proxy can provide HTTPS.

Setup, account commands and checks: [Get started](../GET_STARTED.md).
