"""Shared Pydantic models and contracts between Backend and Container Manager."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")]


class Difficulty(str, Enum):
    WARMUP = "warmup"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class ResourceItem(BaseModel):
    id: str
    name: str
    file: str


class ExerciseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    difficulty: Difficulty
    workspace_dir: str
    grade_timeout_seconds: int = Field(default=120, le=300, gt=0)
    max_evaluations: int = Field(default=3, gt=0)
    evaluation_window_minutes: int = Field(default=60, gt=0)
    resources: List[ResourceItem] = Field(default_factory=list)


class CourseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    deadline: str  # ISO 8601 with timezone


class EvaluatorTestResult(BaseModel):
    id: str
    name: Optional[str] = None
    passed: bool = Field(strict=True)
    message: Optional[str] = None


class EvaluatorOutput(BaseModel):
    schema_version: Literal[1]
    tests: List[EvaluatorTestResult]


class RuntimeState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    GRADING = "grading"
    UNKNOWN = "unknown"


class OperationType(str, Enum):
    START = "start"
    STOP = "stop"
    GRADE = "grade"


class OperationInfo(BaseModel):
    id: str
    type: OperationType
    exercise_id: Optional[str] = None
    started_at: str


class SSHInfo(BaseModel):
    host: str
    port: int = Field(ge=1, le=65535)
    user: str = "student"


class ExerciseRef(BaseModel):
    id: str
    name: str


class EnvironmentResponse(BaseModel):
    state: RuntimeState
    locked: bool = False
    operation: Optional[OperationInfo] = None
    exercise: Optional[ExerciseRef] = None
    ssh: Optional[SSHInfo] = None


class ManagerStartRequest(BaseModel):
    operation_id: Identifier
    exercise_id: Identifier
    ssh_public_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ManagerSSHKeyRequest(BaseModel):
    public_key: str



class ManagerStopRequest(BaseModel):
    operation_id: Identifier


class ManagerGradeRequest(BaseModel):
    operation_id: Identifier
    exercise_id: Identifier


class ManagerGradeResponse(BaseModel):
    operation_id: str
    exercise_id: str
    status: Literal["completed", "error", "interrupted"]
    tests: List[EvaluatorTestResult] = Field(default_factory=list)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None


class ManagerOperation(BaseModel):
    operation_id: Identifier
    type: OperationType
    status: Literal["running", "completed", "failed"]
    started_at: float = Field(ge=0, le=253402300799, allow_inf_nan=False)
    exercise_id: Optional[str] = None
    result: Any = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class ManagerEnvironmentResponse(BaseModel):
    state: RuntimeState
    exercise_id: Optional[str] = None
    ssh: Optional[SSHInfo] = None
    active_operation: Optional[ManagerOperation] = None


class ExerciseBuildReport(BaseModel):
    available: bool
    dev_image_id: Optional[str] = None
    dev_tag: Optional[str] = None
    evaluator_image_id: Optional[str] = None
    evaluator_tag: Optional[str] = None
    error: Optional[str] = None


class ManagerCatalogResponse(BaseModel):
    catalog_hash: str
    available: bool
    phase: Literal["preparing", "ready", "failed"]
    build_report: dict[str, ExerciseBuildReport]


class ErrorDetail(BaseModel):
    code: str
    message: str
    operation_id: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
