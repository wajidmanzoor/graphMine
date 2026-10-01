from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class LLMMode(str, Enum):
    planner = "planner"
    analyst = "analyst"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    interpreting = "interpreting"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class FileRole(str, Enum):
    graph = "graph"
    query_graph = "query_graph"
    motif = "motif"
    updates = "updates"
    left_partition = "left_partition"
    attachment = "attachment"


class VisualizationKind(str, Enum):
    network = "network"
    bar = "bar"
    histogram = "histogram"
    line = "line"
    timeline = "timeline"
    heatmap = "heatmap"
    table = "table"
    metric_cards = "metric_cards"


class SessionRecord(StrictModel):
    id: str = Field(default_factory=lambda: new_id("session"))
    title: str | None = None
    domain_id: str = "general"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SessionCreate(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    domain_id: str = "general"


class DomainProfile(StrictModel):
    id: str
    name: str
    description: str
    common_entities: list[str]
    common_questions: list[str]
    relevant_problem_ids: list[str]
    visualization_priorities: list[VisualizationKind]


class GraphMetadata(StrictModel):
    graph_id: str
    name: str
    directed: bool
    allows_self_loops: bool
    allows_parallel_edges: bool
    vertex_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    density: float = Field(ge=0)
    minimum_degree: int = Field(ge=0)
    maximum_degree: int = Field(ge=0)
    average_degree: float = Field(ge=0)
    isolated_vertex_count: int = Field(ge=0)
    has_weights: bool
    has_timestamps: bool


class StoredFile(StrictModel):
    id: str = Field(default_factory=lambda: new_id("file"))
    session_id: str
    role: FileRole
    original_name: str
    media_type: str | None = None
    source_path: str
    canonical_path: str | None = None
    sha256: str
    size_bytes: int = Field(ge=0)
    metadata: GraphMetadata | dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now)


class FileInfo(StrictModel):
    """Public file metadata; server-local workspace paths never cross the API."""

    id: str
    session_id: str
    role: FileRole
    original_name: str
    media_type: str | None = None
    sha256: str
    size_bytes: int = Field(ge=0)
    metadata: GraphMetadata | dict[str, Any] | None = None
    created_at: datetime

    @classmethod
    def from_stored(cls, record: StoredFile) -> FileInfo:
        return cls.model_validate(
            record.model_dump(exclude={"source_path", "canonical_path"})
        )


JsonScalar = str | int | float | bool | None


class ExecutionPlan(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    session_id: str
    graph_id: str
    problem_id: str
    operation_id: str
    backend_id: str = Field(
        default="auto",
        description="Exact backend ID from the selected operation, or auto.",
    )
    parameters: dict[str, JsonScalar] = Field(
        default_factory=dict,
        description=(
            "Only exact keys from program_instruction.parameters; null means "
            "the optional CLI flag is omitted."
        ),
    )
    optional_outputs: list[str] = Field(
        default_factory=list,
        description=(
            "Exact requested keys from program_instruction.optional_outputs; "
            "do not put output behaviors in parameters."
        ),
    )
    auxiliary_inputs: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "Exact program_instruction.auxiliary_inputs keys mapped to matching "
            "available file IDs."
        ),
    )
    allow_directed_projection: bool = False
    collect_statistics: bool = True
    missing_inputs: list[str] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=1_200)

    @field_validator("optional_outputs")
    @classmethod
    def unique_outputs(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("optional_outputs must not contain duplicates")
        return values


class PlanRequest(StrictModel):
    message: str = Field(min_length=1, max_length=20_000)
    graph_id: str
    backend_id: str | None = None
    parameters: dict[str, JsonScalar] = Field(default_factory=dict)
    optional_outputs: list[str] = Field(default_factory=list)
    auxiliary_inputs: dict[str, list[str]] = Field(default_factory=dict)
    allow_directed_projection: bool = False


class RouteDecision(StrictModel):
    problem_id: str | None = None
    operation_id: str | None = None
    supported: bool = Field(
        description=(
            "True only when the selected problem has library_support.status "
            "equal to 'validated' and exposes the selected operation."
        )
    )
    confidence: float = Field(ge=0, le=1)
    ambiguity: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1, max_length=800)


class PlanningOutcome(StrictModel):
    message: str
    decision: RouteDecision
    plan: ExecutionPlan | None = None


class VisualizationSpec(StrictModel):
    id: str = Field(default_factory=lambda: new_id("view"))
    type: VisualizationKind
    title: str = Field(min_length=1, max_length=200)
    data_ref: str
    encodings: dict[str, str] = Field(default_factory=dict)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    interactions: list[
        Literal[
            "zoom",
            "pan",
            "select_node",
            "select_edge",
            "select_row",
            "filter",
            "brush",
            "time_range",
        ]
    ] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1, le=100_000)
    description: str = ""


class EvidenceItem(StrictModel):
    claim: str
    data_ref: str
    value: Any | None = None


class Interpretation(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    summary: str
    findings: list[str] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(min_length=1)
    suggested_followups: list[str] = Field(min_length=1)
    visualizations: list[VisualizationSpec] = Field(default_factory=list)
    requires_new_execution: bool = False
    proposed_request: str | None = None


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=20_000)
    graph_id: str | None = None
    result_id: str | None = None
    mode: Literal["auto", "planner", "analyst"] = "auto"
    execute: bool = True


class InterpretRequest(StrictModel):
    message: str = Field(
        default="Interpret this result and select useful visualizations.",
        min_length=1,
        max_length=20_000,
    )


class ChatResponse(StrictModel):
    mode: LLMMode
    message: str
    plan: ExecutionPlan | None = None
    interpretation: Interpretation | None = None
    job_id: str | None = None
    result_id: str | None = None


class JobRecord(StrictModel):
    id: str = Field(default_factory=lambda: new_id("job"))
    session_id: str
    plan: ExecutionPlan
    status: JobStatus = JobStatus.queued
    command: list[str] = Field(default_factory=list)
    result_id: str | None = None
    error: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ResultRecord(StrictModel):
    id: str = Field(default_factory=lambda: new_id("result"))
    job_id: str
    session_id: str
    operation_id: str
    payload: dict[str, Any]
    summary: dict[str, Any]
    interpretation: Interpretation | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ConversationEvent(StrictModel):
    sequence: int | None = None
    session_id: str
    job_id: str | None = None
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class CapabilityReport(StrictModel):
    binary_available: bool
    binary_path: str
    graph_gpu_uuid: str | None
    operation_count: int
    validated_backend_count: int
    compiled_backend_count: int
    operations: list[dict[str, Any]]
    error: str | None = None
