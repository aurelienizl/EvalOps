"""Unit tests for course catalog validation and security constraints."""

from pathlib import Path
import pytest

from shared.catalog import (
    CatalogValidationError,
    parse_and_validate_catalog,
)


def _create_exercise_dir(course_dir: Path, exercise_id: str, workspace_dir: str, resource_file: str = None) -> Path:
    """Helper to create minimal valid exercise tree for catalog tests."""
    ex_dir = course_dir / "exercises" / exercise_id
    ex_dir.mkdir(parents=True, exist_ok=True)
    manifest = (
        f"id: {exercise_id}\nname: {exercise_id}\ndifficulty: warmup\n"
        f"workspace_dir: {workspace_dir}\n"
    )
    if resource_file:
        manifest += f"resources:\n  - id: res1\n    name: Res1\n    file: {resource_file}\n"
    (ex_dir / "exercise.yaml").write_text(manifest)
    (ex_dir / "README.md").write_text("# Readme")
    (ex_dir / "dev").mkdir(exist_ok=True)
    (ex_dir / "dev" / "Dockerfile").write_text("FROM scratch")
    (ex_dir / "evaluator").mkdir(exist_ok=True)
    (ex_dir / "evaluator" / "Dockerfile").write_text("FROM scratch")
    return ex_dir


def _create_course_dir(base_dir: Path, course_id: str) -> Path:
    """Helper to create minimal valid course tree."""
    course_dir = base_dir / course_id
    course_dir.mkdir(parents=True, exist_ok=True)
    (course_dir / "course.yaml").write_text(
        f"id: {course_id}\nname: {course_id}\ndeadline: '2026-12-31T23:59:59+00:00'\n"
    )
    return course_dir


def test_valid_real_catalog(courses_path):
    """The real project course catalog parses and passes all validations."""
    catalog = parse_and_validate_catalog(courses_path)
    assert len(catalog.courses) >= 1

    course = next(c for c in catalog.courses.values() if len(c.exercises) > 0)
    assert course.name is not None
    assert len(course.exercises) >= 1

    exercise = course.exercises[0]
    assert exercise.name is not None
    assert exercise.workspace_dir is not None
    assert len(exercise.get_readme_content()) > 0


def test_catalog_rejects_duplicate_exercise_id(tmp_path):
    """Exercise IDs must be globally unique across all courses."""
    c1 = _create_course_dir(tmp_path, "course1")
    _create_exercise_dir(c1, "duplicate-id", "ws1")

    c2 = _create_course_dir(tmp_path, "course2")
    _create_exercise_dir(c2, "duplicate-id", "ws2")

    with pytest.raises(CatalogValidationError, match="Duplicate exercise id 'duplicate-id'"):
        parse_and_validate_catalog(tmp_path)


def test_catalog_rejects_resource_traversal(tmp_path):
    """Resource files escaping the exercise directory are rejected."""
    c1 = _create_course_dir(tmp_path, "course1")
    _create_exercise_dir(c1, "ex1", "ws1", resource_file="../../../etc/passwd")

    with pytest.raises(CatalogValidationError, match="escapes exercise directory"):
        parse_and_validate_catalog(tmp_path)


def test_catalog_rejects_duplicate_workspace_dir(tmp_path):
    """Workspace directories must be globally unique across exercises."""
    c1 = _create_course_dir(tmp_path, "course1")
    _create_exercise_dir(c1, "ex1", "same-workspace")
    _create_exercise_dir(c1, "ex2", "same-workspace")

    with pytest.raises(CatalogValidationError, match="Duplicate workspace_dir 'same-workspace'"):
        parse_and_validate_catalog(tmp_path)


def test_catalog_fingerprint_includes_build_sources_and_resources(tmp_path):
    course = _create_course_dir(tmp_path, "course1")
    exercise = _create_exercise_dir(course, "ex1", "ws1", resource_file="resource.txt")
    source = exercise / "evaluator" / "evaluate.py"
    source.write_text("print('first')")
    resource = exercise / "resource.txt"
    resource.write_text("first resource")
    original_hash = parse_and_validate_catalog(tmp_path).catalog_hash
    source.write_text("print('second')")
    source_hash = parse_and_validate_catalog(tmp_path).catalog_hash
    assert source_hash != original_hash
    resource.write_text("second resource")
    assert parse_and_validate_catalog(tmp_path).catalog_hash != source_hash


def test_catalog_dynamic_order_and_no_points(tmp_path):
    """Exercises and courses do not require points/order and display in dynamic discovery order."""
    course = _create_course_dir(tmp_path, "course-dyn")
    ex1 = _create_exercise_dir(course, "zeta", "ws-zeta")
    ex2 = _create_exercise_dir(course, "alpha", "ws-alpha")

    catalog = parse_and_validate_catalog(tmp_path)
    c = catalog.get_course("course-dyn")
    assert c is not None
    assert len(c.exercises) == 2
    exercise_ids = [e.id for e in c.exercises]
    assert set(exercise_ids) == {"zeta", "alpha"}
    for ex in c.exercises:
        assert not hasattr(ex, "points")
        assert not hasattr(ex, "order")
    assert not hasattr(c, "order")
