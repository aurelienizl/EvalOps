"""Synchronous student operations and their persistent evaluation records."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from shared.catalog import Catalog, Exercise
from shared.contracts import (
    EnvironmentResponse,
    ExerciseRef,
    ManagerEnvironmentResponse,
    ManagerGradeResponse,
    OperationInfo,
    OperationType,
    RuntimeState,
)

from .db import (
    check_evaluation_quota,
    connect_db,
    create_initial_evaluation,
    finalize_evaluation,
    get_evaluation,
    get_student_runtime,
    mark_exercise_completed,
    set_student_runtime,
)
from .services.container_client import ContainerManagerClient

CONTAINER_MANAGER_URL = os.environ.get(
    "CONTAINER_MANAGER_URL", "http://container_manager:8001"
)
OPERATION_STATES = {
    OperationType.START: RuntimeState.STARTING,
    OperationType.STOP: RuntimeState.STOPPING,
    OperationType.GRADE: RuntimeState.GRADING,
}


class RuntimeManager:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self._student_locks: dict[str, threading.Lock] = {}
        self._dict_lock = threading.Lock()
        self.container_client = ContainerManagerClient(CONTAINER_MANAGER_URL)

    def close(self) -> None:
        self.container_client.close()

    def get_student_lock(self, student_id: str) -> threading.Lock:
        with self._dict_lock:
            return self._student_locks.setdefault(student_id, threading.Lock())

    def is_student_locked(self, student_id: str) -> bool:
        return self.get_student_lock(student_id).locked()

    def get_manager_catalog(self) -> dict[str, Any]:
        return self.container_client.get_catalog()

    def _reconcile_runtime(
        self, student_id: str, runtime: Any, manager: ManagerEnvironmentResponse
    ) -> Any:
        """Reconcile an operation left by a timeout or a restart, under the student lock."""
        active = manager.active_operation
        if (
            active
            and active.operation_id == runtime["operation_id"]
            and active.status == "running"
        ):
            return runtime

        if runtime["operation_type"] == "grade":
            with connect_db() as conn:
                evaluation = get_evaluation(conn, runtime["operation_id"])
            if evaluation is not None and evaluation["status"] == "running":
                if (
                    active
                    and active.operation_id == runtime["operation_id"]
                    and active.status == "completed"
                ):
                    try:
                        result = self._validate_grade(
                            active.result,
                            runtime["operation_id"],
                            runtime["operation_exercise_id"],
                        )
                    except HTTPException as exc:
                        error = exc.detail["error"]
                        self._record_evaluation_error(
                            runtime["operation_id"], error["code"], error["message"]
                        )
                    else:
                        if result.status == "completed":
                            self._save_evaluation(student_id, result)
                        else:
                            self._record_evaluation_error(
                                result.operation_id,
                                result.error_code or "EVALUATOR_FAILED",
                                result.error_message or "Erreur d'évaluation",
                                result.status,
                            )
                else:
                    self._record_evaluation_error(
                        runtime["operation_id"],
                        "EVALUATION_INTERRUPTED",
                        "L'évaluation a été interrompue",
                        "interrupted",
                    )

        self._clear_runtime(student_id, runtime["operation_id"])
        return None

    def get_environment(self, student_id: str) -> EnvironmentResponse:
        lock = self.get_student_lock(student_id)
        acquired = lock.acquire(blocking=False)
        try:
            manager = self.container_client.get_student_environment(student_id)
            with connect_db() as conn:
                runtime = get_student_runtime(conn, student_id)
            if acquired and runtime is not None and manager is not None:
                runtime = self._reconcile_runtime(student_id, runtime, manager)

            if manager is None:
                return EnvironmentResponse(
                    state=RuntimeState.UNKNOWN,
                    locked=not acquired or runtime is not None,
                )
            if runtime is not None:
                operation_type = OperationType(runtime["operation_type"])
                return EnvironmentResponse(
                    state=OPERATION_STATES[operation_type],
                    locked=True,
                    operation=OperationInfo(
                        id=runtime["operation_id"],
                        type=operation_type,
                        exercise_id=runtime["operation_exercise_id"],
                        started_at=runtime["operation_started_at"],
                    ),
                )
            if (
                manager.active_operation
                and manager.active_operation.status == "running"
            ):
                operation = manager.active_operation
                return EnvironmentResponse(
                    state=OPERATION_STATES[operation.type],
                    locked=True,
                    operation=OperationInfo(
                        id=operation.operation_id,
                        type=operation.type,
                        exercise_id=operation.exercise_id,
                        started_at=datetime.fromtimestamp(
                            operation.started_at, UTC
                        ).isoformat(),
                    ),
                )
            exercise = (
                self.catalog.get_exercise(manager.exercise_id)
                if manager.exercise_id
                else None
            )
            return EnvironmentResponse(
                state=manager.state,
                locked=not acquired,
                ssh=manager.ssh,
                exercise=ExerciseRef(id=exercise.id, name=exercise.name)
                if exercise
                else None,
            )
        finally:
            if acquired:
                lock.release()

    @staticmethod
    def _conflict(operation_id: str | None = None) -> HTTPException:
        return ContainerManagerClient._error(
            409,
            "OPERATION_IN_PROGRESS",
            "Une opération est déjà en cours",
            operation_id,
        )

    @staticmethod
    def _clear_runtime(student_id: str, operation_id: str) -> None:
        with connect_db() as conn:
            conn.execute(
                "DELETE FROM student_runtime WHERE student_id = ? AND operation_id = ?",
                (student_id, operation_id),
            )

    @contextmanager
    def _student_operation(
        self, student_id: str, operation_type: str, exercise_id: str | None
    ) -> Iterator[str]:
        lock = self.get_student_lock(student_id)
        if not lock.acquire(blocking=False):
            raise self._conflict()
        operation_id = str(uuid.uuid4())
        claimed = False
        keep_pending = False
        try:
            with connect_db() as conn:
                existing = get_student_runtime(conn, student_id)
            if existing is not None:
                manager = self.container_client.get_student_environment(student_id)
                if manager is not None:
                    existing = self._reconcile_runtime(student_id, existing, manager)
                if existing is not None:
                    raise self._conflict(existing["operation_id"])

            with connect_db() as conn:
                # Keep checking and recording the persistent operation atomic.
                conn.execute("BEGIN IMMEDIATE")
                existing = get_student_runtime(conn, student_id)
                if existing is not None:
                    raise self._conflict(existing["operation_id"])
                set_student_runtime(
                    conn,
                    student_id,
                    operation_id,
                    operation_type,
                    exercise_id,
                    OPERATION_STATES[OperationType(operation_type)].value,
                )
                conn.commit()
                claimed = True
            yield operation_id
        except HTTPException as exc:
            keep_pending = (
                isinstance(exc.detail, dict)
                and exc.detail.get("error", {}).get("code")
                == "CONTAINER_MANAGER_TIMEOUT"
            )
            raise
        except sqlite3.Error:
            # Keep the operation available for reconciliation if saving its result fails.
            keep_pending = True
            raise
        finally:
            try:
                if claimed and not keep_pending:
                    self._clear_runtime(student_id, operation_id)
            finally:
                lock.release()

    def unlock_student(self, student_id: str) -> None:
        lock = self.get_student_lock(student_id)
        if not lock.acquire(blocking=False):
            raise self._conflict()
        try:
            manager = self.container_client.get_student_environment(student_id)
            if manager is None:
                raise ContainerManagerClient._error(
                    503,
                    "CONTAINER_MANAGER_UNAVAILABLE",
                    "Gestionnaire de conteneurs indisponible",
                )
            if (
                manager.active_operation
                and manager.active_operation.status == "running"
            ):
                raise self._conflict(manager.active_operation.operation_id)
            with connect_db() as conn:
                runtime = get_student_runtime(conn, student_id)
            if runtime is not None:
                self._reconcile_runtime(student_id, runtime, manager)
        finally:
            lock.release()

    def _get_available_exercise(self, exercise_id: str) -> Exercise:
        exercise = self.catalog.get_exercise(exercise_id)
        if not exercise:
            raise ContainerManagerClient._error(
                404, "EXERCISE_NOT_FOUND", "Exercice introuvable"
            )
        course = self.catalog.get_course(exercise.course_id)
        if course and course.is_expired():
            raise ContainerManagerClient._error(
                403, "DEADLINE_EXPIRED", "La date limite pour ce cours est dépassée"
            )
        return exercise

    def start_environment(
        self, student_id: str, exercise_id: str, ssh_public_key: str
    ) -> dict[str, Any]:
        self._get_available_exercise(exercise_id)
        if not ssh_public_key:
            raise ContainerManagerClient._error(
                422,
                "SSH_KEY_REQUIRED",
                "Une clé publique SSH est requise pour démarrer",
            )
        with self._student_operation(student_id, "start", exercise_id) as operation_id:
            data = self.container_client.start_student_environment(
                student_id, operation_id, exercise_id, ssh_public_key
            )
            try:
                environment = EnvironmentResponse.model_validate(data)
                if (
                    environment.state != RuntimeState.RUNNING
                    or not environment.exercise
                    or environment.exercise.id != exercise_id
                    or not environment.ssh
                ):
                    raise ValueError("Unexpected started environment")
            except (ValidationError, ValueError) as exc:
                raise ContainerManagerClient._error(
                    502,
                    "INVALID_MANAGER_RESPONSE",
                    "Réponse de démarrage invalide",
                    operation_id,
                ) from exc
            return environment.model_dump(mode="json")

    def stop_environment(self, student_id: str) -> dict[str, Any]:
        with self._student_operation(student_id, "stop", None) as operation_id:
            data = self.container_client.stop_student_environment(
                student_id, operation_id
            )
            if data.get("state") != "stopped":
                raise ContainerManagerClient._error(
                    502,
                    "INVALID_MANAGER_RESPONSE",
                    "Réponse d'arrêt invalide",
                    operation_id,
                )
            return EnvironmentResponse(state=RuntimeState.STOPPED).model_dump(
                mode="json"
            )

    @staticmethod
    def _validate_grade(
        data: Any, operation_id: str, exercise_id: str
    ) -> ManagerGradeResponse:
        try:
            result = ManagerGradeResponse.model_validate(data)
            if result.operation_id != operation_id or result.exercise_id != exercise_id:
                raise ValueError("Mismatched evaluation identity")
            test_ids = [test.id for test in result.tests]
            if len(test_ids) != len(set(test_ids)):
                raise ValueError("Duplicate evaluation tests")
            return result
        except (ValidationError, ValueError) as exc:
            raise ContainerManagerClient._error(
                502,
                "INVALID_MANAGER_RESPONSE",
                "Résultat d'évaluation invalide",
                operation_id,
            ) from exc

    @staticmethod
    def _record_evaluation_error(
        operation_id: str, code: str, message: str, evaluation_status: str = "error"
    ) -> None:
        with connect_db() as conn:
            finalize_evaluation(
                conn,
                operation_id,
                evaluation_status,
                None,
                None,
                None,
                None,
                code,
                message,
            )

    @staticmethod
    def _save_evaluation(
        student_id: str, result: ManagerGradeResponse
    ) -> dict[str, Any]:
        tests = [
            {
                "id": test.id,
                "name": test.name or test.id,
                "passed": test.passed,
                "message": test.message,
            }
            for test in result.tests
        ]
        passed = sum(test.passed for test in result.tests)
        total = len(tests)
        percentage = round(100.0 * passed / total, 2) if total else 0.0
        success = total > 0 and passed == total
        with connect_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            finalize_evaluation(
                conn,
                result.operation_id,
                "completed",
                passed,
                total,
                percentage,
                json.dumps(tests, ensure_ascii=False),
            )
            if success:
                mark_exercise_completed(
                    conn, student_id, result.exercise_id, result.operation_id
                )
            conn.commit()
        return {
            "id": result.operation_id,
            "exercise_id": result.exercise_id,
            "status": "completed",
            "passed": passed,
            "total": total,
            "percentage": percentage,
            "success": success,
            "tests": tests,
        }

    def grade_environment(self, student_id: str, exercise_id: str) -> dict[str, Any]:
        exercise = self._get_available_exercise(exercise_id)
        with self._student_operation(student_id, "grade", exercise_id) as operation_id:
            with connect_db() as conn:
                quota = check_evaluation_quota(
                    conn,
                    student_id,
                    exercise_id,
                    exercise.max_evaluations,
                    exercise.evaluation_window_minutes,
                )
                if quota["remaining"] == 0 and quota["reset_in_seconds"] > 0:
                    retry_after = quota["reset_in_seconds"]
                    raise HTTPException(
                        status_code=429,
                        headers={"Retry-After": str(retry_after)},
                        detail={
                            "error": {
                                "code": "EVALUATION_RATE_LIMITED",
                                "retry_after_seconds": retry_after,
                                "message": f"Limite d'évaluations atteinte. Réessayez dans {(retry_after + 59) // 60} minute(s).",
                            }
                        },
                    )
                create_initial_evaluation(
                    conn,
                    operation_id,
                    student_id,
                    exercise_id,
                    exercise.name,
                    exercise.points,
                )
            try:
                data = self.container_client.grade_student_environment(
                    student_id,
                    operation_id,
                    exercise_id,
                    timeout=exercise.grade_timeout_seconds + 60.0,
                )
                result = self._validate_grade(data, operation_id, exercise_id)
            except Exception as exc:
                error = (
                    exc.detail.get("error", {})
                    if isinstance(exc, HTTPException) and isinstance(exc.detail, dict)
                    else {}
                )
                if error.get("code") != "CONTAINER_MANAGER_TIMEOUT":
                    self._record_evaluation_error(
                        operation_id,
                        error.get("code", "EVALUATOR_FAILED"),
                        error.get("message", "Erreur d'évaluation"),
                    )
                raise
            if result.status != "completed":
                code = result.error_code or "EVALUATOR_FAILED"
                message = result.error_message or "Erreur d'évaluation"
                self._record_evaluation_error(
                    operation_id, code, message, result.status
                )
                raise ContainerManagerClient._error(
                    504 if code == "EVALUATION_TIMEOUT" else 502,
                    code,
                    message,
                    operation_id,
                )
            evaluation = self._save_evaluation(student_id, result)
            return {
                "environment": EnvironmentResponse(
                    state=RuntimeState.STOPPED
                ).model_dump(mode="json"),
                "evaluation": evaluation,
            }

    def update_student_ssh_key(self, student_id: str, ssh_public_key: str) -> None:
        self.container_client.update_ssh_key(student_id, ssh_public_key)

    def get_evaluation_snapshot(self, student_id: str, evaluation_id: str) -> bytes:
        try:
            return self.container_client.get_snapshot(student_id, evaluation_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                raise ContainerManagerClient._error(
                    404, "SNAPSHOT_NOT_FOUND", "Archive de snapshot introuvable"
                ) from exc
            raise
