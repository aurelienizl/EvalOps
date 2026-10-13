"""Docker image builder for exercise environments and evaluators."""

from __future__ import annotations

import logging
from typing import Any, Dict

import docker

from shared.catalog import Catalog

logger = logging.getLogger(__name__)


class BuildManager:
    def __init__(self, docker_client: docker.DockerClient, instance_id: str, apt_cache_url: str = ""):
        self.client = docker_client
        self.instance_id = instance_id
        self.apt_cache_url = apt_cache_url
        self.report: Dict[str, Dict[str, Any]] = {}
        self.is_ready = False
        self.phase = "preparing"

    def run_all_builds(self, catalog: Catalog) -> Dict[str, Dict[str, Any]]:
        self.phase = "preparing"
        self.is_ready = False
        self.report.clear()

        buildargs: Dict[str, str] = {}
        if self.apt_cache_url:
            buildargs["http_proxy"] = self.apt_cache_url
            buildargs["HTTP_PROXY"] = self.apt_cache_url

        exercises = list(catalog.exercises_by_id.values())
        logger.info(f"Starting sequential builds for {len(exercises)} exercises...")

        for ex in exercises:
            ex_report: Dict[str, Any] = {
                "dev_image_id": None,
                "dev_tag": None,
                "evaluator_image_id": None,
                "evaluator_tag": None,
                "available": False,
                "error": None,
            }

            tags = (
                ("dev", f"evalops-{self.instance_id}-{ex.id}-dev:latest"),
                ("evaluator", f"evalops-{self.instance_id}-{ex.id}-eval:latest"),
            )
            try:
                for kind, tag in tags:
                    logger.info(f"Building {kind} image for exercise {ex.id}...")
                    build_kwargs: Dict[str, Any] = {
                        "path": str(getattr(ex, f"{kind}_context_path")),
                        "dockerfile": "Dockerfile",
                        "tag": tag,
                        "rm": True,
                    }
                    if buildargs:
                        build_kwargs["buildargs"] = buildargs
                    image, _ = self.client.images.build(**build_kwargs)
                    ex_report[f"{kind}_image_id"] = image.id
                    ex_report[f"{kind}_tag"] = tag

                ex_report["available"] = True
                logger.info(f"Successfully built images for exercise {ex.id}")

            except Exception as e:
                logger.error(f"Failed to build images for exercise {ex.id}: {e}", exc_info=True)
                ex_report["error"] = str(e)
                ex_report["available"] = False

            self.report[ex.id] = ex_report

        self.phase = "ready"
        self.is_ready = True
        failed = sum(not report["available"] for report in self.report.values())
        logger.info("Builds finished: %d exercises available, %d unavailable", len(exercises) - failed, failed)
        return self.report
