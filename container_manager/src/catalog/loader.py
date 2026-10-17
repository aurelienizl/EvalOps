"""Course discovery, validation, image preparation and catalog publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class ResourceDefinition:
    source_id: str  # Manifest-local ID; SQL resource IDs remain existing UUIDs.
    name: str
    file_path: Path


@dataclass(frozen=True)
class ExerciseDefinition:
    id: str
    course_id: str
    name: str
    difficulty: Literal["warmup", "easy", "medium", "hard"]
    workspace_dir: str
    grade_timeout_seconds: int
    max_evaluations: int
    evaluation_window_minutes: int
    directory: Path
    subject: str
    resources: tuple[ResourceDefinition, ...]


@dataclass(frozen=True)
class CourseDefinition:
    id: str
    name: str
    deadline: datetime | None
    exercises: tuple[ExerciseDefinition, ...]


@dataclass(frozen=True)
class PreparedExercise:
    definition: ExerciseDefinition
    environment_image: str
    evaluator_image: str


def discover_catalog(courses_root):
    import re
    import yaml

    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        result = {}
        for key, value in node.value:
            key = loader.construct_object(key, deep=deep)
            if key in result:
                raise ValueError(f"Duplicate YAML key: {key}")
            result[key] = loader.construct_object(value, deep=deep)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    slug = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
    courses = []
    ids = set()
    workspaces = set()
    for p in courses_root.rglob("*"):
        if p.is_symlink():
            raise ValueError(f"Catalog symlink: {p}")

    def read(path, required, optional):
        data = yaml.load(path.read_text(), Loader=UniqueLoader)
        if (
            not isinstance(data, dict)
            or not required <= data.keys()
            or data.keys() - required - optional
        ):
            raise ValueError(f"Invalid manifest fields: {path}")
        if (
            not isinstance(data["id"], str)
            or not slug.fullmatch(data["id"])
            or data["id"] != path.parent.name
        ):
            raise ValueError(f"Invalid ID: {path}")
        if not isinstance(data["name"], str) or not 0 < len(data["name"].strip()) <= 255:
            raise ValueError(f"Invalid name: {path}")
        return data

    for directory in sorted(
        p for p in courses_root.iterdir() if p.is_dir() and not p.name.startswith(".")
    ):
        data = read(directory / "course.yaml", {"id", "name"}, {"deadline"})
        deadline = datetime.fromisoformat(data["deadline"]) if data.get("deadline") else None
        if deadline and deadline.utcoffset() is None:
            raise ValueError(f"Timezone missing: {directory}")
        exercises = []
        for folder in sorted(
            p
            for p in (directory / "exercises").iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ):
            ex = read(
                folder / "exercise.yaml",
                {
                    "id",
                    "name",
                    "difficulty",
                    "workspace_dir",
                    "grade_timeout_seconds",
                    "max_evaluations",
                    "evaluation_window_minutes",
                },
                {"resources"},
            )
            if (
                ex["id"] in ids
                or ex["workspace_dir"] in workspaces
                or not slug.fullmatch(ex["workspace_dir"])
            ):
                raise ValueError(f"Duplicate/invalid exercise workspace: {folder}")
            ids.add(ex["id"])
            workspaces.add(ex["workspace_dir"])
            if ex["difficulty"] not in ("warmup", "easy", "medium", "hard"):
                raise ValueError(f"Invalid difficulty: {folder}")
            for key in ("grade_timeout_seconds", "max_evaluations", "evaluation_window_minutes"):
                if type(ex[key]) is not int or ex[key] <= 0:
                    raise ValueError(f"Invalid {key}: {folder}")
            if not 5 <= ex["grade_timeout_seconds"] <= 600:
                raise ValueError(f"Invalid timeout: {folder}")
            for required in (
                "README.md",
                "dev/Dockerfile",
                "dev/entrypoint.sh",
                "evaluator/Dockerfile",
                "evaluator/evaluate.py",
            ):
                if not (folder / required).is_file():
                    raise ValueError(f"Missing {required}: {folder}")
            subject = (folder / "README.md").read_text()
            if not subject.strip():
                raise ValueError(f"Empty subject: {folder}")
            resources = []
            resource_ids = set()
            for r in ex.get("resources", []):
                if (
                    set(r) != {"id", "name", "file"}
                    or not slug.fullmatch(r["id"])
                    or r["id"] in resource_ids
                ):
                    raise ValueError(f"Invalid resource: {folder}")
                resource_ids.add(r["id"])
                path = Path(r["file"])
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or not (folder / path).resolve().is_relative_to(folder.resolve())
                    or not (folder / path).is_file()
                ):
                    raise ValueError(f"Invalid resource path: {folder}")
                resources.append(ResourceDefinition(r["id"], r["name"], (folder / path).resolve()))
            exercises.append(
                ExerciseDefinition(
                    ex["id"],
                    data["id"],
                    ex["name"],
                    ex["difficulty"],
                    ex["workspace_dir"],
                    ex["grade_timeout_seconds"],
                    ex["max_evaluations"],
                    ex["evaluation_window_minutes"],
                    folder,
                    subject,
                    tuple(resources),
                )
            )
        courses.append(CourseDefinition(data["id"], data["name"], deadline, tuple(exercises)))
    if not courses or not ids:
        raise ValueError("Catalog is empty")
    return courses


async def prepare_images(client, courses):
    import hashlib
    from ..runtime.docker import build_image, wrap_evaluator_image

    result = []
    for course in courses:
        for ex in course.exercises:
            digest = hashlib.sha256()
            for p in sorted(ex.directory.rglob("*")):
                if p.is_file():
                    digest.update(str(p.relative_to(ex.directory)).encode() + b"\0")
                    digest.update(str(p.stat().st_mode & 0o777).encode() + b"\0")
                    digest.update(p.read_bytes())
            tag = digest.hexdigest()[:24]
            env = await build_image(client, ex.directory / "dev", f"evalops-env-{ex.id}:{tag}")
            evaluator = await build_image(
                client, ex.directory / "evaluator", f"evalops-eval-{ex.id}:{tag}"
            )
            evaluator = await wrap_evaluator_image(client, evaluator)
            result.append(PreparedExercise(ex, env, evaluator))
    return result


async def publish_catalog(connection, courses, exercises):
    from uuid import uuid5, NAMESPACE_URL

    async with connection.transaction():
        for course in courses:
            await connection.execute(
                """INSERT INTO courses(id,name,deadline) VALUES($1,$2,$3)
                ON CONFLICT(id) DO UPDATE SET name=$2,deadline=$3""",
                course.id,
                course.name,
                course.deadline,
            )
        for prepared in exercises:
            ex = prepared.definition
            await connection.execute(
                """INSERT INTO exercises(id,course_id,name,subject,difficulty,environment_image,evaluator_image,
                workspace_dir,grade_timeout_seconds,max_evaluations,evaluation_window_minutes)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT(id) DO UPDATE SET
                name=$3,subject=$4,difficulty=$5,environment_image=$6,evaluator_image=$7,
                workspace_dir=$8,grade_timeout_seconds=$9,max_evaluations=$10,evaluation_window_minutes=$11""",
                ex.id,
                ex.course_id,
                ex.name,
                ex.subject,
                ex.difficulty,
                prepared.environment_image,
                prepared.evaluator_image,
                ex.workspace_dir,
                ex.grade_timeout_seconds,
                ex.max_evaluations,
                ex.evaluation_window_minutes,
            )
            await connection.execute("DELETE FROM exercise_resources WHERE exercise_id=$1", ex.id)
            root = ex.directory.parent.parent.parent
            for r in ex.resources:
                await connection.execute(
                    "INSERT INTO exercise_resources(id,exercise_id,name,file_path) VALUES($1,$2,$3,$4)",
                    uuid5(NAMESPACE_URL, f"evalops/{ex.id}/{r.source_id}"),
                    ex.id,
                    r.name,
                    str(r.file_path.relative_to(root)),
                )


async def load_catalog(connection, client, settings):
    import asyncio

    courses = await asyncio.to_thread(discover_catalog, settings.courses_root)
    prepared = await prepare_images(client, courses)
    await publish_catalog(connection, courses, prepared)
