-- SQLite Schema for EvalOps Platform
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS students (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student',
    ssh_public_key TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS student_runtime (
    student_id TEXT PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    operation_id TEXT,
    operation_type TEXT,
    operation_exercise_id TEXT,
    operation_started_at TEXT,
    manager_instance_id TEXT,
    phase TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_student ON sessions(student_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    exercise_id TEXT NOT NULL,
    exercise_name TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    passed INTEGER,
    total INTEGER,
    percentage REAL,
    tests_json TEXT,
    error_code TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_evaluations_student_exercise 
ON evaluations(student_id, exercise_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_evaluations_created_at ON evaluations(created_at DESC);

CREATE TABLE IF NOT EXISTS student_exercises (
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    exercise_id TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    successful_evaluation_id TEXT NOT NULL REFERENCES evaluations(id),
    PRIMARY KEY (student_id, exercise_id)
);

PRAGMA user_version = 1;
