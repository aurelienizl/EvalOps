"""Shared catalog loading, validation, and querying module."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from shared.contracts import CourseManifest, Difficulty, ExerciseManifest, ResourceItem

IDENTIFIER_REGEX = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class CatalogValidationError(Exception):
    """Raised when catalog fails validation rules."""
    pass


class Exercise:
    def __init__(
        self,
        manifest: ExerciseManifest,
        course_id: str,
        exercise_dir: Path,
    ):
        self.manifest = manifest
        self.course_id = course_id
        self.exercise_dir = exercise_dir

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def difficulty(self) -> Difficulty:
        return self.manifest.difficulty

    @property
    def workspace_dir(self) -> str:
        return self.manifest.workspace_dir

    @property
    def grade_timeout_seconds(self) -> int:
        return self.manifest.grade_timeout_seconds

    @property
    def max_evaluations(self) -> int:
        return self.manifest.max_evaluations

    @property
    def evaluation_window_minutes(self) -> int:
        return self.manifest.evaluation_window_minutes

    @property
    def resources(self) -> List[ResourceItem]:
        return self.manifest.resources

    @property
    def readme_path(self) -> Path:
        return self.exercise_dir / "README.md"

    @property
    def dev_dockerfile_path(self) -> Path:
        return self.exercise_dir / "dev" / "Dockerfile"

    @property
    def evaluator_dockerfile_path(self) -> Path:
        return self.exercise_dir / "evaluator" / "Dockerfile"

    @property
    def dev_context_path(self) -> Path:
        return self.exercise_dir / "dev"

    @property
    def evaluator_context_path(self) -> Path:
        return self.exercise_dir / "evaluator"

    def get_readme_content(self) -> str:
        if self.readme_path.is_file():
            return self.readme_path.read_text(encoding="utf-8")
        return ""

    def resolve_resource_file(self, resource_id: str) -> Optional[Path]:
        for res in self.manifest.resources:
            if res.id == resource_id:
                raw_path = (self.exercise_dir / res.file).resolve()
                exercise_root = self.exercise_dir.resolve()
                # Ensure resolved path is strictly within exercise_root
                try:
                    raw_path.relative_to(exercise_root)
                except ValueError:
                    return None
                if raw_path.is_file():
                    return raw_path
        return None


class Course:
    def __init__(
        self,
        manifest: CourseManifest,
        course_dir: Path,
        exercises: List[Exercise],
        deadline_utc: datetime,
    ):
        self.manifest = manifest
        self.course_dir = course_dir
        self.exercises = list(exercises)
        self.deadline_utc = deadline_utc

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def deadline_iso(self) -> str:
        return self.manifest.deadline

    def is_expired(self, current_time: Optional[datetime] = None) -> bool:
        now = current_time or datetime.now(timezone.utc)
        return now > self.deadline_utc


class Catalog:
    def __init__(self, courses_path: Path):
        self.courses_path = courses_path
        self.courses: Dict[str, Course] = {}
        self.exercises_by_id: Dict[str, Exercise] = {}
        self.catalog_hash: str = ""

    def get_course(self, course_id: str) -> Optional[Course]:
        return self.courses.get(course_id)

    def get_exercise(self, exercise_id: str) -> Optional[Exercise]:
        return self.exercises_by_id.get(exercise_id)

    def list_courses(self) -> List[Course]:
        return list(self.courses.values())


def _hash_file(hasher, file_path: Path, catalog_root: Path) -> None:
    try:
        file_path.resolve().relative_to(catalog_root)
    except ValueError as error:
        raise CatalogValidationError(f"Catalog file escapes courses directory: {file_path}") from error
    hasher.update(file_path.relative_to(catalog_root).as_posix().encode("utf-8") + b"\0")
    hasher.update(hashlib.sha256(file_path.read_bytes()).digest())


def parse_and_validate_catalog(courses_path: Path | str) -> Catalog:
    path = Path(courses_path).resolve()
    if not path.is_dir():
        raise CatalogValidationError(f"Courses directory does not exist: {path}")

    catalog = Catalog(path)
    hasher = hashlib.sha256()

    course_ids: set[str] = set()
    exercise_ids: set[str] = set()
    workspace_dirs: set[str] = set()

    course_dirs = [d for d in path.iterdir() if d.is_dir()]

    for cdir in course_dirs:
        course_yaml_path = cdir / "course.yaml"
        if not course_yaml_path.is_file():
            continue

        try:
            with open(course_yaml_path, "r", encoding="utf-8") as f:
                c_data = yaml.safe_load(f)
        except Exception as e:
            raise CatalogValidationError(f"Invalid YAML in {course_yaml_path}: {e}")

        if not isinstance(c_data, dict):
            raise CatalogValidationError(f"Course manifest must be a dictionary in {course_yaml_path}")

        try:
            course_manifest = CourseManifest(**c_data)
        except Exception as e:
            raise CatalogValidationError(f"Validation error in {course_yaml_path}: {e}")

        if not IDENTIFIER_REGEX.fullmatch(course_manifest.id):
            raise CatalogValidationError(f"Invalid course id format '{course_manifest.id}' in {course_yaml_path}")

        if course_manifest.id in course_ids:
            raise CatalogValidationError(f"Duplicate course id '{course_manifest.id}' found in {course_yaml_path}")
        course_ids.add(course_manifest.id)

        # Validate deadline format and parse UTC
        try:
            dl = datetime.fromisoformat(course_manifest.deadline)
            if dl.tzinfo is None:
                raise ValueError("Deadline must include a timezone offset")
            deadline_utc = dl.astimezone(timezone.utc)
        except Exception as e:
            raise CatalogValidationError(f"Invalid deadline '{course_manifest.deadline}' in {course_yaml_path}: {e}")

        _hash_file(hasher, course_yaml_path, path)

        # Load exercises
        exercises_dir = cdir / "exercises"
        exercises_for_course: List[Exercise] = []

        if exercises_dir.is_dir():
            ex_dirs = [d for d in exercises_dir.iterdir() if d.is_dir()]
            for exdir in ex_dirs:
                ex_yaml_path = exdir / "exercise.yaml"
                if not ex_yaml_path.is_file():
                    continue

                try:
                    with open(ex_yaml_path, "r", encoding="utf-8") as f:
                        ex_data = yaml.safe_load(f)
                except Exception as e:
                    raise CatalogValidationError(f"Invalid YAML in {ex_yaml_path}: {e}")

                if not isinstance(ex_data, dict):
                    raise CatalogValidationError(f"Exercise manifest must be a dictionary in {ex_yaml_path}")

                try:
                    ex_manifest = ExerciseManifest(**ex_data)
                except Exception as e:
                    raise CatalogValidationError(f"Validation error in {ex_yaml_path}: {e}")

                # Identifier regex
                if not IDENTIFIER_REGEX.fullmatch(ex_manifest.id):
                    raise CatalogValidationError(f"Invalid exercise id '{ex_manifest.id}' in {ex_yaml_path}")
                if not IDENTIFIER_REGEX.fullmatch(ex_manifest.workspace_dir):
                    raise CatalogValidationError(f"Invalid workspace_dir '{ex_manifest.workspace_dir}' in {ex_yaml_path}")

                # Global uniqueness
                if ex_manifest.id in exercise_ids:
                    raise CatalogValidationError(f"Duplicate exercise id '{ex_manifest.id}' across catalog")
                exercise_ids.add(ex_manifest.id)

                if ex_manifest.workspace_dir in workspace_dirs:
                    raise CatalogValidationError(f"Duplicate workspace_dir '{ex_manifest.workspace_dir}' across catalog")
                workspace_dirs.add(ex_manifest.workspace_dir)

                # Validate README, dev Dockerfile, evaluator Dockerfile
                readme_p = exdir / "README.md"
                if not readme_p.is_file():
                    raise CatalogValidationError(f"Missing README.md in {exdir}")

                dev_dock = exdir / "dev" / "Dockerfile"
                if not dev_dock.is_file():
                    raise CatalogValidationError(f"Missing dev/Dockerfile in {exdir}")

                eval_dock = exdir / "evaluator" / "Dockerfile"
                if not eval_dock.is_file():
                    raise CatalogValidationError(f"Missing evaluator/Dockerfile in {exdir}")

                # Validate resources path traversal
                for res in ex_manifest.resources:
                    res_path = (exdir / res.file).resolve()
                    try:
                        res_path.relative_to(exdir.resolve())
                    except ValueError:
                        raise CatalogValidationError(f"Resource '{res.id}' escapes exercise directory: {res.file}")
                    if not res_path.is_file():
                        raise CatalogValidationError(f"Resource file does not exist: {res_path}")

                _hash_file(hasher, ex_yaml_path, path)
                _hash_file(hasher, readme_p, path)
                for context in (exdir / "dev", exdir / "evaluator"):
                    for source_file in sorted(context.rglob("*")):
                        if source_file.is_file():
                            _hash_file(hasher, source_file, path)
                for resource in ex_manifest.resources:
                    _hash_file(hasher, exdir / resource.file, path)

                exercise_obj = Exercise(
                    manifest=ex_manifest,
                    course_id=course_manifest.id,
                    exercise_dir=exdir,
                )
                exercises_for_course.append(exercise_obj)
                catalog.exercises_by_id[exercise_obj.id] = exercise_obj

        course_obj = Course(
            manifest=course_manifest,
            course_dir=cdir,
            exercises=exercises_for_course,
            deadline_utc=deadline_utc,
        )
        catalog.courses[course_obj.id] = course_obj

    catalog.catalog_hash = hasher.hexdigest()
    return catalog
