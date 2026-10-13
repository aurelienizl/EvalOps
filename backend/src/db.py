"""Database access layer for SQLite with WAL mode, foreign keys, and connection management."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_database_path() -> Path:
    db_env = os.environ.get("DATABASE_PATH", "/data/app.db")
    p = Path(db_env)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def connect_db(db_path: Optional[Path | str] = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path) if db_path else get_database_path()
    conn = sqlite3.connect(
        str(path),
        timeout=5.0,
        isolation_level=None,  # autocommit by default; use explicit BEGIN/COMMIT for transactions
    )
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(db_path: Optional[Path | str] = None) -> None:
    path = Path(db_path) if db_path else get_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect_db(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


# --- Student / User Operations ---

def create_student(
    conn: sqlite3.Connection,
    student_id: str,
    email: str,
    password_hash: str,
    role: str = "student",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO students (id, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
        (student_id, email.lower().strip(), password_hash, role, now),
    )


def get_student_by_id(conn: sqlite3.Connection, student_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()


def get_student_by_email(conn: sqlite3.Connection, email: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM students WHERE email = ?", (email.lower().strip(),)).fetchone()


def update_student_password(conn: sqlite3.Connection, student_id: str, new_password_hash: str) -> None:
    conn.execute("UPDATE students SET password_hash = ? WHERE id = ?", (new_password_hash, student_id))


def update_student_ssh_key(conn: sqlite3.Connection, student_id: str, public_key: str) -> None:
    conn.execute("UPDATE students SET ssh_public_key = ? WHERE id = ?", (public_key.strip(), student_id))


def update_student_role(conn: sqlite3.Connection, student_id: str, role: str) -> None:
    conn.execute("UPDATE students SET role = ? WHERE id = ?", (role, student_id))


def list_users(
    conn: sqlite3.Connection,
    search: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[sqlite3.Row], int]:
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    where_clauses = []
    params: List[Any] = []

    if search:
        where_clauses.append("email LIKE ?")
        params.append(f"%{search.strip().lower()}%")

    if role:
        where_clauses.append("role = ?")
        params.append(role)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    count_row = conn.execute(f"SELECT COUNT(*) as total FROM students {where_sql}", params).fetchone()
    total = count_row["total"] if count_row else 0

    query = f"SELECT id, email, role, ssh_public_key, created_at FROM students {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    rows = conn.execute(query, params + [limit, offset]).fetchall()
    return rows, total


# --- Session Operations ---

def create_session(conn: sqlite3.Connection, token_hash: str, student_id: str, csrf_token: str, expires_at: str) -> None:
    conn.execute(
        "INSERT INTO sessions (token_hash, student_id, csrf_token, expires_at) VALUES (?, ?, ?, ?)",
        (token_hash, student_id, csrf_token, expires_at),
    )


def get_session(conn: sqlite3.Connection, token_hash: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sessions WHERE token_hash = ?",
        (token_hash,),
    ).fetchone()


def delete_session(conn: sqlite3.Connection, token_hash: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def delete_all_student_sessions(conn: sqlite3.Connection, student_id: str) -> None:
    conn.execute("DELETE FROM sessions WHERE student_id = ?", (student_id,))


def cleanup_expired_sessions(conn: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))


# --- Student Runtime (Persistent Operations Lock) ---

def get_student_runtime(conn: sqlite3.Connection, student_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM student_runtime WHERE student_id = ?", (student_id,)).fetchone()


def set_student_runtime(
    conn: sqlite3.Connection,
    student_id: str,
    operation_id: str,
    operation_type: str,
    exercise_id: Optional[str],
    phase: str,
    manager_instance_id: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO student_runtime (
            student_id, operation_id, operation_type, operation_exercise_id, 
            operation_started_at, manager_instance_id, phase
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id) DO UPDATE SET
            operation_id = excluded.operation_id,
            operation_type = excluded.operation_type,
            operation_exercise_id = excluded.operation_exercise_id,
            operation_started_at = excluded.operation_started_at,
            manager_instance_id = excluded.manager_instance_id,
            phase = excluded.phase
        """,
        (student_id, operation_id, operation_type, exercise_id, now, manager_instance_id, phase),
    )


def clear_student_runtime(conn: sqlite3.Connection, student_id: str) -> None:
    conn.execute("DELETE FROM student_runtime WHERE student_id = ?", (student_id,))


# --- Evaluation Operations ---

def create_initial_evaluation(
    conn: sqlite3.Connection,
    evaluation_id: str,
    student_id: str,
    exercise_id: str,
    exercise_name: str,
    exercise_points: int,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO evaluations (
            id, student_id, exercise_id, exercise_name, exercise_points,
            status, created_at
        ) VALUES (?, ?, ?, ?, ?, 'running', ?)
        """,
        (evaluation_id, student_id, exercise_id, exercise_name, exercise_points, now),
    )


def finalize_evaluation(
    conn: sqlite3.Connection,
    evaluation_id: str,
    status: str,
    passed: Optional[int],
    total: Optional[int],
    percentage: Optional[float],
    tests_json: Optional[str],
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE evaluations SET
            status = ?,
            finished_at = ?,
            passed = ?,
            total = ?,
            percentage = ?,
            tests_json = ?,
            error_code = ?,
            error_message = ?
        WHERE id = ?
        """,
        (status, now, passed, total, percentage, tests_json, error_code, error_message, evaluation_id),
    )


def get_evaluation(conn: sqlite3.Connection, evaluation_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM evaluations WHERE id = ?", (evaluation_id,)).fetchone()


def list_student_evaluations(
    conn: sqlite3.Connection,
    student_id: str,
    exercise_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> List[sqlite3.Row]:
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    query = "SELECT * FROM evaluations WHERE student_id = ?"
    parameters = (student_id,)
    if exercise_id:
        query += " AND exercise_id = ?"
        parameters += (exercise_id,)
    return conn.execute(
        query + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
        parameters + (limit, offset),
    ).fetchall()


def parse_utc_dt(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def get_evaluation_submission_dates(
    conn: sqlite3.Connection,
    student_id: str,
    exercise_id: str,
    limit: int,
) -> List[str]:
    """Returns recent submission timestamps in chronological order."""
    rows = conn.execute(
        """
        SELECT created_at FROM evaluations
        WHERE student_id = ? AND exercise_id = ?
        ORDER BY created_at DESC LIMIT ?
        """,
        (student_id, exercise_id, limit),
    ).fetchall()
    return [r["created_at"] for r in reversed(rows)]


def check_evaluation_quota(
    conn: sqlite3.Connection,
    student_id: str,
    exercise_id: str,
    max_evaluations: int,
    window_minutes: int,
) -> Dict[str, Any]:
    """
    Checks the evaluation quota:
    - If total submissions < limit: allowed immediately.
    - If total submissions >= limit: checks the submission at (current - limit)
      and compares to current date. If within window, rate-limited.
    """
    submissions = get_evaluation_submission_dates(conn, student_id, exercise_id, max_evaluations)
    now = datetime.now(timezone.utc)
    window_seconds = window_minutes * 60

    # If limit reached, check submission at (current - limit)
    if len(submissions) >= max_evaluations:
        ref_dt = parse_utc_dt(submissions[-max_evaluations])
        elapsed = (now - ref_dt).total_seconds()
        if elapsed < window_seconds:
            return {
                "max_evaluations": max_evaluations,
                "window_minutes": window_minutes,
                "used": max_evaluations,
                "remaining": 0,
                "reset_in_seconds": max(1, int(window_seconds - elapsed)),
            }

    # Not rate-limited: count active submissions in the window
    cutoff = now - timedelta(minutes=window_minutes)
    used = sum(1 for s in submissions[-max_evaluations:] if parse_utc_dt(s) >= cutoff)
    return {
        "max_evaluations": max_evaluations,
        "window_minutes": window_minutes,
        "used": used,
        "remaining": max(0, max_evaluations - used),
        "reset_in_seconds": 0,
    }



# --- Student Exercise Progress Operations ---

def get_completed_exercise_ids(conn: sqlite3.Connection, student_id: str) -> set[str]:
    cur = conn.execute("SELECT exercise_id FROM student_exercises WHERE student_id = ?", (student_id,))
    return {row["exercise_id"] for row in cur.fetchall()}


def mark_exercise_completed(
    conn: sqlite3.Connection,
    student_id: str,
    exercise_id: str,
    evaluation_id: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO student_exercises (student_id, exercise_id, completed_at, successful_evaluation_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(student_id, exercise_id) DO NOTHING
        """,
        (student_id, exercise_id, now, evaluation_id),
    )


# --- Admin Query Operations ---

def list_all_evaluations(
    conn: sqlite3.Connection,
    student_id: Optional[str] = None,
    exercise_id: Optional[str] = None,
    eval_status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[sqlite3.Row], int]:
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    where_clauses = []
    params: List[Any] = []

    if student_id:
        where_clauses.append("student_id = ?")
        params.append(student_id)

    if exercise_id:
        where_clauses.append("exercise_id = ?")
        params.append(exercise_id)

    if eval_status:
        where_clauses.append("status = ?")
        params.append(eval_status)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    count_row = conn.execute(f"SELECT COUNT(*) as total FROM evaluations {where_sql}", params).fetchone()
    total = count_row["total"] if count_row else 0

    query = f"""
        SELECT id, student_id, exercise_id, exercise_name, exercise_points, status,
               created_at, finished_at, passed, total, percentage, tests_json, error_code, error_message
        FROM evaluations {where_sql}
        ORDER BY created_at DESC LIMIT ? OFFSET ?
    """
    rows = conn.execute(query, params + [limit, offset]).fetchall()
    return rows, total


def list_all_student_runtimes(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        """
        SELECT r.student_id, s.email, r.operation_id, r.operation_type,
               r.operation_exercise_id, r.operation_started_at, r.phase
        FROM student_runtime r
        JOIN students s ON r.student_id = s.id
        ORDER BY r.operation_started_at DESC
        """
    ).fetchall()


def get_platform_stats(conn: sqlite3.Connection) -> Dict[str, Any]:
    total_users = conn.execute("SELECT COUNT(*) as count FROM students").fetchone()["count"]
    total_evals = conn.execute("SELECT COUNT(*) as count FROM evaluations").fetchone()["count"]
    passed_evals = conn.execute("SELECT COUNT(*) as count FROM evaluations WHERE percentage = 100.0").fetchone()["count"]
    completed_exercises = conn.execute("SELECT COUNT(*) as count FROM student_exercises").fetchone()["count"]
    active_operations = conn.execute("SELECT COUNT(*) as count FROM student_runtime").fetchone()["count"]

    return {
        "total_users": total_users,
        "total_evaluations": total_evals,
        "passed_evaluations": passed_evals,
        "completed_exercises": completed_exercises,
        "active_operations": active_operations,
    }

