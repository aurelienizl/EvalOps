"""HTTP client for communicating with the Container Manager service."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from shared.contracts import ManagerCatalogResponse, ManagerEnvironmentResponse

logger = logging.getLogger("backend.services.container_client")


class ContainerManagerClient:
    """Dedicated HTTP client wrapping all Container Manager REST endpoints."""

    def __init__(self, base_url: str, timeout: httpx.Timeout | None = None):
        if timeout is None:
            timeout = httpx.Timeout(connect=5.0, read=360.0, write=10.0, pool=10.0)
        self._timeout = timeout
        self.http_client = httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        self.http_client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        operation_id: str | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        request_timeout = httpx.Timeout(
            timeout,
            connect=self._timeout.connect,
            write=self._timeout.write,
            pool=self._timeout.pool,
        )
        try:
            response = getattr(self.http_client, method.lower())(
                path, timeout=request_timeout, **kwargs
            )
        except (httpx.ReadTimeout, httpx.WriteTimeout) as exc:
            raise self._error(
                504,
                "CONTAINER_MANAGER_TIMEOUT",
                "Le gestionnaire de conteneurs n'a pas répondu à temps",
                operation_id,
            ) from exc
        except httpx.RequestError as exc:
            raise self._error(
                502,
                "CONTAINER_MANAGER_UNAVAILABLE",
                "Gestionnaire de conteneurs indisponible",
                operation_id,
            ) from exc

        if response.status_code != 200:
            error = {}
            try:
                body = response.json()
                if isinstance(body, dict) and isinstance(body.get("error"), dict):
                    error = body["error"]
            except ValueError:
                pass
            status_code = response.status_code if response.status_code >= 400 else 502
            raise self._error(
                status_code,
                error.get("code") or "CONTAINER_MANAGER_ERROR",
                error.get("message") or "Erreur du gestionnaire de conteneurs",
                operation_id,
            )
        return response

    @staticmethod
    def _error(
        status_code: int, code: str, message: str, operation_id: str | None = None
    ) -> HTTPException:
        error = {"code": code, "message": message}
        if operation_id:
            error["operation_id"] = operation_id
        return HTTPException(status_code=status_code, detail={"error": error})

    @classmethod
    def _json(
        cls, response: httpx.Response, operation_id: str | None = None
    ) -> dict[str, Any]:
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise TypeError("Expected an object")
            return data
        except (TypeError, ValueError) as exc:
            raise cls._error(
                502,
                "INVALID_MANAGER_RESPONSE",
                "Réponse du gestionnaire de conteneurs invalide",
                operation_id,
            ) from exc

    def get_health(self) -> dict[str, Any]:
        """Queries health of the container manager."""
        return self._json(self._request("GET", "/v1/health", timeout=5.0))

    def get_catalog(self) -> dict[str, Any]:
        """Queries container manager build status and catalog hash."""
        try:
            data = self._json(self._request("GET", "/v1/catalog", timeout=10.0))
            return ManagerCatalogResponse.model_validate(data).model_dump(mode="json")
        except (HTTPException, ValidationError) as exc:
            logger.warning("Failed to query manager catalog: %s", exc)
            return {}

    def get_student_environment(
        self, student_id: str
    ) -> ManagerEnvironmentResponse | None:
        """Queries environment status for a given student."""
        try:
            data = self._json(
                self._request(
                    "GET", f"/v1/students/{student_id}/environment", timeout=10.0
                )
            )
            return ManagerEnvironmentResponse.model_validate(data)
        except (HTTPException, ValidationError) as exc:
            logger.warning("Error querying manager environment: %s", exc)
            return None

    def start_student_environment(
        self, student_id: str, operation_id: str, exercise_id: str, ssh_public_key: str
    ) -> dict[str, Any]:
        """Requests starting an environment for a student."""
        response = self._request(
            "POST",
            f"/v1/students/{student_id}/start",
            operation_id=operation_id,
            json={
                "operation_id": operation_id,
                "exercise_id": exercise_id,
                "ssh_public_key": ssh_public_key,
            },
            timeout=90.0,
        )
        return self._json(response, operation_id)

    def stop_student_environment(
        self, student_id: str, operation_id: str
    ) -> dict[str, Any]:
        """Requests stopping a running student container."""
        response = self._request(
            "POST",
            f"/v1/students/{student_id}/stop",
            operation_id=operation_id,
            json={"operation_id": operation_id},
            timeout=45.0,
        )
        return self._json(response, operation_id)

    def grade_student_environment(
        self,
        student_id: str,
        operation_id: str,
        exercise_id: str,
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        """Requests running evaluator against student code."""
        response = self._request(
            "POST",
            f"/v1/students/{student_id}/grade",
            operation_id=operation_id,
            json={"operation_id": operation_id, "exercise_id": exercise_id},
            timeout=timeout,
        )
        return self._json(response, operation_id)

    def update_ssh_key(self, student_id: str, ssh_public_key: str) -> None:
        """Pushes student SSH key to their persistent workspace volume."""
        self._request(
            "POST",
            f"/v1/students/{student_id}/ssh-key",
            json={"public_key": ssh_public_key},
            timeout=15.0,
        )

    def get_snapshot(self, student_id: str, evaluation_id: str) -> bytes:
        """Downloads tarball snapshot of evaluated code."""
        return self._request(
            "GET",
            f"/v1/students/{student_id}/evaluations/{evaluation_id}/snapshot",
            timeout=30.0,
        ).content
