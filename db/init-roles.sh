#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    -v backend_password="$BACKEND_DB_PASSWORD" -v manager_password="$MANAGER_DB_PASSWORD" <<'SQL'
CREATE ROLE evalops_backend LOGIN PASSWORD :'backend_password';
CREATE ROLE evalops_manager LOGIN PASSWORD :'manager_password';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO evalops_backend,evalops_manager;
GRANT SELECT ON courses,exercises,exercise_resources,evaluation_tests,user_completed_exercises TO evalops_backend;
GRANT SELECT,INSERT,UPDATE ON users,environments,evaluations TO evalops_backend;
GRANT SELECT,INSERT,UPDATE,DELETE ON sessions TO evalops_backend;
GRANT SELECT,INSERT,UPDATE,DELETE ON courses,exercises,exercise_resources,environments,evaluations,evaluation_tests,user_completed_exercises TO evalops_manager;
GRANT SELECT(id,ssh_key),UPDATE(id) ON users TO evalops_manager;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO evalops_manager;
SQL
