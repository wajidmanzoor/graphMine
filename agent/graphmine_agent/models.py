from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    vega_lite = "vega_lite"


class SessionRecord(StrictModel):
    id: str = Field(default_factory=lambda: new_id("session"))
    title: str | None = None
    domain_id: str = "general"
    participant_id: str | None = Field(default=None, max_length=80)
    archived: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SessionUpdate(StrictModel):
    """Rename or archive a conversation; omitted fields stay unchanged."""

    title: str | None = Field(default=None, max_length=200)
    archived: bool | None = None


class SessionCreate(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    domain_id: str = "general"
    participant_id: str | None = Field(default=None, max_length=80)


class DomainProfile(StrictModel):
    id: str
    name: str
    description: str
    common_entities: list[str]
    common_questions: list[str]
    relevant_topic_ids: list[str]
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
    semantic_context: dict[str, Any] = Field(default_factory=dict)


class StoredFile(StrictModel):
    backend_id: Literal["local", "iu-remote"] | None = None
    id: str = Field(default_factory=lambda: new_id("file"))
    session_id: str
    role: FileRole
    original_name: str
    media_type: str | None = None
    source_path: str
    canonical_path: str | None = None
    sha256: str
    size_bytes: int = Field(ge=0)
    provenance: dict[str, Any] = Field(default_factory=dict)
    metadata: GraphMetadata | dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now)


class FileInfo(StrictModel):
    """Public file metadata; server-local workspace paths never cross the API."""

    backend_id: Literal["local", "iu-remote"] | None = None

    id: str
    session_id: str
    role: FileRole
    original_name: str
    media_type: str | None = None
    sha256: str
    size_bytes: int = Field(ge=0)
    provenance: dict[str, Any] = Field(default_factory=dict)
    metadata: GraphMetadata | dict[str, Any] | None = None
    created_at: datetime

    @classmethod
    def from_stored(cls, record: StoredFile) -> FileInfo:
        return cls.model_validate(
            record.model_dump(exclude={"source_path", "canonical_path"})
        )


JsonScalar = str | int | float | bool | None
# Nested groups are validated against the problem-specific ID contract.
JsonParameter = JsonScalar | list[list[JsonScalar]]


class DataFilter(StrictModel):
    target: Literal["vertices", "edges"]
    field: str = Field(min_length=1, max_length=120)
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in"]
    value: JsonScalar | list[JsonScalar]


class ApplicationIntent(StrictModel):
    objective: str = Field(default="", max_length=1500)
    entity_type: str | None = None
    relationship_meaning: str | None = None
    filters: list[DataFilter] = Field(default_factory=list, max_length=12)
    filter_mode: Literal["inherit", "replace", "clear"] = "inherit"
    requires_edge_weights: bool = False
    weight_attribute: str | None = Field(default=None, max_length=120)
    weight_usage: Literal["path_length", "strength", "other"] | None = None
    requires_direction: bool = False
    pattern_vertex_count: int | None = Field(default=None, ge=1, le=100)
    pattern_edges: list[list[int]] = Field(default_factory=list, max_length=30)
    time_unit: Literal["seconds", "milliseconds", "native", "unspecified"] = (
        "unspecified"
    )
    time_window: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    assumptions: list[str] = Field(default_factory=list, max_length=6)


class AnalysisTask(StrictModel):
    question: str = Field(min_length=1, max_length=1500)
    topic_id: str | None = Field(default=None, description="Optional documentation hint; inferred from the runnable problem.")
    problem_id: str


class DataInspection(StrictModel):
    target: Literal["vertices", "edges"]
    filters: list[DataFilter] = Field(default_factory=list, max_length=6)
    fields: list[str] = Field(default_factory=list, max_length=8)
    limit: int = Field(default=10, ge=1, le=20)


class TurnDecision(StrictModel):
    action: Literal["explain", "analyze", "clarify"]
    request: str = Field(min_length=1, max_length=3000)
    explanation: str = Field(default="", max_length=800)


class ExecutionPlan(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    session_id: str
    graph_id: str
    topic_id: str | None = Field(default=None, description="Optional documentation hint; inferred from the runnable problem.")
    problem_id: str
    backend_id: str = Field(
        default="auto",
        description="Exact backend ID from the selected problem, or auto.",
    )
    parameters: dict[str, JsonParameter] = Field(
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
    application_intent: ApplicationIntent | None = None

    @field_validator("optional_outputs")
    @classmethod
    def unique_outputs(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("optional_outputs must not contain duplicates")
        return values


class PlanConfiguration(StrictModel):
    """Only tool choices need generation; executable identity is server-owned."""

    backend_id: str = "auto"
    parameters: dict[str, JsonParameter] = Field(default_factory=dict)
    optional_outputs: list[str] = Field(default_factory=list)
    auxiliary_inputs: dict[str, list[str]] = Field(default_factory=dict)
    rationale: str = Field(default="", max_length=800)


class PlanDraft(StrictModel):
    """The detailed planner can refuse AFTER seeing the actual tool contract."""

    status: Literal["ready", "needs_information", "unsupported"]
    message: str = Field(min_length=1, max_length=1500)
    plan: PlanConfiguration | None = None

    @model_validator(mode="after")
    def executable_only_when_ready(self):
        if (self.status == "ready") != (self.plan is not None):
            raise ValueError("only a ready outcome may contain an execution plan")
        return self


class PlanRequest(StrictModel):
    message: str = Field(min_length=1, max_length=20_000)
    graph_id: str
    result_id: str | None = None
    backend_id: str | None = None
    parameters: dict[str, JsonParameter] = Field(default_factory=dict)
    optional_outputs: list[str] = Field(default_factory=list)
    auxiliary_inputs: dict[str, list[str]] = Field(default_factory=dict)
    allow_directed_projection: bool = False


class RouteDecision(StrictModel):
    topic_id: str | None = Field(
        default=None,
        description=(
            "Exact formal topic ID when intent is recognized, including an "
            "unsupported topic; null only for ambiguous or unrecognized intent."
        ),
    )
    problem_id: str | None = Field(
        default=None,
        description=(
            "Exact runnable problem for a supported topic; null for an "
            "unsupported, ambiguous, or unrecognized request."
        ),
    )
    supported: bool = Field(
        description=(
            "True only when the selected topic has library_support.status "
            "equal to 'validated' and exposes the selected problem."
        )
    )
    confidence: float = Field(ge=0, le=1)
    ambiguity: list[str] = Field(
        default_factory=list,
        description="Only unresolved user choices phrased as questions. Empty for multiple clear, independently answerable questions.",
    )
    missing_information: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1, max_length=800)
    intent: ApplicationIntent = Field(default_factory=ApplicationIntent)
    additional_analyses: list[AnalysisTask] = Field(default_factory=list, max_length=3)
    inspections: list[DataInspection] = Field(default_factory=list, max_length=2)


class PlanningOutcome(StrictModel):
    message: str
    decision: RouteDecision
    plan: ExecutionPlan | None = None
    status: Literal["ready", "needs_information", "unsupported"] = "needs_information"
    plans: list[ExecutionPlan] = Field(default_factory=list)

    @model_validator(mode="after")
    def safe_outcome(self):
        if self.status != "ready" and (self.plan is not None or self.plans):
            raise ValueError("non-ready outcomes cannot expose executable plans")
        if self.status == "ready" and self.plan is None:
            raise ValueError("a ready outcome requires an execution plan")
        return self


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
    vega_lite: dict[str, Any] | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    view_spec: ViewSpec | None = None


class ViewEncoding(StrictModel):
    """An encoding is data, never an expression or executable chart grammar."""

    field: str | None = Field(default=None, max_length=256)
    value: str | float | bool | None = None
    scale: Literal["categorical", "linear", "sqrt", "log1p", "symlog", "sequential", "diverging", "constant"] = "constant"
    range_px: list[float] = Field(default_factory=list, max_length=2)
    domain: list[float] = Field(default_factory=list, max_length=2)
    density: Literal["all", "selected_and_ranked", "none"] = "all"
    categories: list[dict[str, Any]] = Field(default_factory=list, max_length=256)


class ViewLayout(StrictModel):
    name: Literal["force", "hierarchical", "concentric", "circle", "grid", "clustered", "bipartite", "radial", "computed", "none"] = "force"
    seed: int = 0
    sides: list[str] = Field(default_factory=list, max_length=2)
    positions_source: Literal["browser", "saved", "server"] = "browser"
    alternates: list[str] = Field(default_factory=list, max_length=3)


class ViewChart(StrictModel):
    id: str = Field(max_length=80)
    chart: Literal["bar", "histogram", "scatter", "line", "heatmap", "barcode", "route", "metrics", "gallery", "sankey"]
    title: str = Field(max_length=200)
    dataset: str = "rows"
    x: str | None = None
    y: str | None = None
    select: Literal["entity", "edge", "item", "group", "pair", "none"] = "item"


class ViewLimits(StrictModel):
    shown_vertices: int = Field(default=0, ge=0)
    total_vertices: int = Field(default=0, ge=0)
    shown_edges: int = Field(default=0, ge=0)
    total_edges: int = Field(default=0, ge=0)
    sampled: bool = False
    strategy: str = "recorded witness first, then saved input order"
    collection_complete: bool = True


class ViewSpec(StrictModel):
    """Versioned presentation of immutable evidence. Old versions stay replayable."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    rules_version: str = "2026-11-18.3"
    profile: str
    view: Literal["graph", "matrix", "meta_graph", "small_multiples", "barcode", "spectrum", "histogram", "coordinates", "mapping", "scatter", "metric", "table"] = "graph"
    title: str = Field(max_length=200)
    layout: ViewLayout = Field(default_factory=ViewLayout)
    nodes: dict[str, ViewEncoding] = Field(default_factory=dict)
    edges: dict[str, ViewEncoding] = Field(default_factory=dict)
    legend: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    linked: list[ViewChart] = Field(default_factory=list, max_length=8)
    alternates: list[str] = Field(default_factory=list, max_length=16)
    emphasis: dict[str, Any] = Field(default_factory=dict)
    limits: ViewLimits = Field(default_factory=ViewLimits)
    rules_applied: list[str] = Field(default_factory=list, max_length=64)
    provenance: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list, max_length=24)
    renderer: Literal["cytoscape", "cytoscape-webgl"] = "cytoscape"
    field_roles: dict[str, dict[str, Any]] = Field(default_factory=dict)


class EvidenceItem(StrictModel):
    claim: str
    data_ref: str
    value: Any | None = None


class FollowupAction(StrictModel):
    id: str
    label: str
    kind: Literal["show_view", "ask"]
    view_id: str | None = None
    request: str | None = None

    @model_validator(mode="after")
    def valid_target(self):
        if self.kind == "show_view" and (not self.view_id or self.request):
            raise ValueError("view actions require only a view target")
        if self.kind == "ask" and (not self.request or self.view_id):
            raise ValueError("question actions require only a request")
        return self


class GroundedStatement(StrictModel):
    text: str = Field(min_length=1, max_length=2400)
    fact_ids: list[str] = Field(min_length=1, max_length=12)


class VegaLiteDraft(StrictModel):
    """The model supplies a full specification; data is bound by the server."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1600)
    spec_json: str = Field(min_length=2, max_length=60000)
    fact_ids: list[str] = Field(min_length=1, max_length=12)


class Interpretation(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    summary: str
    findings: list[str] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(min_length=1)
    suggested_followups: list[str] = Field(min_length=1)
    followup_actions: list[FollowupAction] = Field(default_factory=list)
    visualizations: list[VisualizationSpec] = Field(default_factory=list)
    requires_new_execution: bool = False
    proposed_request: str | None = None
    hypotheses: list[str] = Field(default_factory=list)
    explanation: list[GroundedStatement] = Field(default_factory=list)


class GroundedNarrative(StrictModel):
    """Evidence-linked prose and custom charts alongside the computed answer."""

    fact_ids: list[str] = Field(min_length=1, max_length=8)
    hypotheses: list[str] = Field(default_factory=list, max_length=3)
    suggested_followups: list[str] = Field(default_factory=list, max_length=3)
    followup_ids: list[str] = Field(default_factory=list, max_length=3)
    view_ids: list[str] = Field(default_factory=list, max_length=4)
    summary: GroundedStatement | None = None
    findings: list[GroundedStatement] = Field(default_factory=list, max_length=8)
    charts: list[VegaLiteDraft] = Field(default_factory=list, max_length=4)
    analysis_request: str | None = Field(default=None, max_length=2000)
    analysis_problem_ids: list[str] = Field(default_factory=list, max_length=4)


class ChartTemplateRequest(StrictModel):
    """The analyst can request a bounded template using declared dataset fields."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1600)
    chart: Literal["bar", "histogram", "scatter", "line", "heatmap"]
    dataset: str = Field(min_length=1, max_length=160)
    x: str = Field(min_length=1, max_length=256)
    y: str | None = Field(default=None, max_length=256)
    color: str | None = Field(default=None, max_length=256)
    fact_ids: list[str] = Field(min_length=1, max_length=12)


class TemplateNarrative(GroundedNarrative):
    """New inference schema. GroundedNarrative remains for historical replay."""

    charts: list[ChartTemplateRequest] = Field(default_factory=list, max_length=1)


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=20_000)
    graph_id: str | None = None
    result_id: str | None = None
    mode: Literal["auto", "planner", "analyst"] = "auto"
    execute: bool = True
    allow_directed_projection: bool = False


class InterpretRequest(StrictModel):
    message: str = Field(
        default="Interpret this result and select useful visualizations.",
        min_length=1,
        max_length=20_000,
    )


class ChatResponse(StrictModel):
    mode: LLMMode
    message: str
    planning_status: Literal["ready", "needs_information", "unsupported"] | None = None
    plan: ExecutionPlan | None = None
    interpretation: Interpretation | None = None
    interpretation_source: Literal["llm", "offline_rules", "fallback"] | None = None
    job_id: str | None = None
    result_id: str | None = None
    turn_id: str | None = None
    feedback_id: str | None = None
    command: str | None = None
    download_url: str | None = None
    job_ids: list[str] = Field(default_factory=list)


class FeedbackCreate(StrictModel):
    what_went_wrong: str = Field(min_length=1, max_length=20_000)
    expected_behavior: str | None = Field(default=None, min_length=1, max_length=20_000)
    category: Literal["feedback", "correction", "rating", "note"] = "feedback"
    rating: int | None = Field(default=None, ge=1, le=5, strict=True)
    turn_id: str | None = None
    job_id: str | None = None
    result_id: str | None = None
    source: Literal["user", "assistant_evaluation"] = "user"

    @model_validator(mode="after")
    def required_annotation_fields(self):
        if self.category == "rating" and self.rating is None:
            raise ValueError("rating annotations require a score from 1 to 5")
        if self.category == "correction" and not self.expected_behavior:
            raise ValueError("corrections require the expected answer")
        return self

    @field_validator("what_went_wrong", "expected_behavior")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("feedback must not be blank")
        return value.strip()


class FeedbackRecord(FeedbackCreate):
    id: str = Field(default_factory=lambda: new_id("feedback"))
    session_id: str
    created_at: datetime = Field(default_factory=utc_now)
    context: dict[str, Any] = Field(default_factory=dict)


class JobRecord(StrictModel):
    backend_id: Literal["local", "iu-remote"] | None = None
    id: str = Field(default_factory=lambda: new_id("job"))
    session_id: str
    plan: ExecutionPlan
    turn_id: str | None = None
    analysis_id: str | None = None
    step_index: int = 0
    step_count: int = 1
    status: JobStatus = JobStatus.queued
    command: list[str] = Field(default_factory=list)
    result_id: str | None = None
    error: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ResultRecord(StrictModel):
    backend_id: Literal["local", "iu-remote"] | None = None
    id: str = Field(default_factory=lambda: new_id("result"))
    job_id: str
    session_id: str
    problem_id: str
    payload: dict[str, Any]
    summary: dict[str, Any]
    answer: dict[str, Any] = Field(default_factory=dict)
    interpretation: Interpretation | None = None
    interpretation_source: Literal["llm", "offline_rules", "fallback"] | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ConversationEvent(StrictModel):
    sequence: int | None = None
    session_id: str
    job_id: str | None = None
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ConversationEventPage(StrictModel):
    active_backend: Literal["local", "iu-remote"] | None = None
    events: list[ConversationEvent]
    after: int
    last_sequence: int
    has_more: bool
    turn_numbers: dict[str, int] = Field(default_factory=dict)


class CapabilityReport(StrictModel):
    binary_available: bool
    binary_path: str
    library_version: str | None = None
    graph_gpu_uuid: str | None
    problem_count: int
    validated_backend_count: int
    compiled_backend_count: int
    problems: list[dict[str, Any]]
    error: str | None = None
    backend_correctness_exclusions: dict[str, dict[str, str]] = Field(
        default_factory=dict
    )
