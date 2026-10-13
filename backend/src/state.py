"""Process-local service objects, initialized by the application lifespan."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.catalog import Catalog

    from .runtime import RuntimeManager

_catalog: Catalog | None = None
_runtime_manager: RuntimeManager | None = None


def get_catalog() -> Catalog | None:
    return _catalog


def get_runtime_manager() -> RuntimeManager | None:
    return _runtime_manager


def set_catalog(catalog: Catalog | None) -> None:
    global _catalog
    _catalog = catalog


def set_runtime_manager(manager: RuntimeManager | None) -> None:
    global _runtime_manager
    _runtime_manager = manager
