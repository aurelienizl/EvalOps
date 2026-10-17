-- Extension pour générer des UUID si version < PG 13 (intégrée par défaut sur PG 13+)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- ENUMS
-- ============================================================

CREATE TYPE user_role AS ENUM ('student', 'admin');
CREATE TYPE exercise_difficulty AS ENUM ('warmup', 'easy', 'medium', 'hard');
CREATE TYPE evaluation_status AS ENUM ('running', 'completed', 'failed', 'timeout');
CREATE TYPE test_status AS ENUM ('passed', 'failed', 'error');
CREATE TYPE environment_status AS ENUM ('starting', 'running', 'grading', 'stopping', 'stopped');


-- ============================================================
-- FONCTION & TRIGGER POUR AUTO-UPDATE 'updated_at'
-- ============================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- 1. UTILISATEURS & SESSIONS
-- ============================================================

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role user_role NOT NULL DEFAULT 'student',
    ssh_key TEXT,
    avatar TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trigger_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) UNIQUE NOT NULL, -- Hash SHA-256 (64 caractères hexa)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_token_hash ON sessions(token_hash);


-- ============================================================
-- 2. COURS, EXERCICES & RESSOURCES
-- ============================================================

CREATE TABLE courses (
    id VARCHAR(64) PRIMARY KEY,          -- Slug unique (ex: 'intro-c')
    name VARCHAR(255) NOT NULL,
    deadline TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trigger_courses_updated_at
BEFORE UPDATE ON courses
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE exercises (
    id VARCHAR(64) PRIMARY KEY,          -- Slug unique (ex: 'fibo-c')
    course_id VARCHAR(64) NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    subject TEXT NOT NULL,
    difficulty exercise_difficulty NOT NULL,
    
    -- Images Docker pré-construites
    environment_image VARCHAR(255) NOT NULL,
    evaluator_image VARCHAR(255) NOT NULL,
    
    workspace_dir VARCHAR(128) UNIQUE NOT NULL,
    grade_timeout_seconds INTEGER NOT NULL DEFAULT 60 CHECK (grade_timeout_seconds > 0),
    max_evaluations INTEGER NOT NULL DEFAULT 3 CHECK (max_evaluations > 0),
    evaluation_window_minutes INTEGER NOT NULL DEFAULT 60 CHECK (evaluation_window_minutes > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trigger_exercises_updated_at
BEFORE UPDATE ON exercises
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_exercises_course_id ON exercises(course_id);

CREATE TABLE exercise_resources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exercise_id VARCHAR(64) NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_exercise_resources_exercise_id ON exercise_resources(exercise_id);


-- ============================================================
-- 3. ÉVALUATIONS & TESTS
-- ============================================================

CREATE TABLE evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exercise_id VARCHAR(64) NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    status evaluation_status NOT NULL DEFAULT 'running',
    
    is_success BOOLEAN NOT NULL DEFAULT FALSE,
    passed_tests INTEGER NOT NULL DEFAULT 0,
    total_tests INTEGER NOT NULL DEFAULT 0,
    
    error_code VARCHAR(64),
    error_message TEXT,
    snapshot_archive_path TEXT,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX idx_evaluations_user_exercise ON evaluations(user_id, exercise_id);
CREATE INDEX idx_evaluations_status ON evaluations(status);

CREATE TABLE evaluation_tests (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    evaluation_id UUID NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    status test_status NOT NULL,
    
    return_code INTEGER,
    stdout_diff TEXT,
    stderr_diff TEXT,
    execution_time_ms INTEGER,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_evaluation_tests_evaluation_id ON evaluation_tests(evaluation_id);


-- ============================================================
-- 4. VALIDATION PERMANENTE (Consultation instantanée)
-- ============================================================

CREATE TABLE user_completed_exercises (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exercise_id VARCHAR(64) NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    successful_evaluation_id UUID NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, exercise_id)
);


-- ============================================================
-- 5. RUNTIME / ÉTAT DES CONTENEURS (Partagé)
-- ============================================================

CREATE TABLE environments (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    exercise_id VARCHAR(64) NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    container_id VARCHAR(128),
    ssh_port INTEGER,
    status environment_status NOT NULL,
    current_operation_id UUID,
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);