from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .calculation_limits import DEFAULT_EXECUTION_TIMEOUT_SECONDS


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _integer(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


def _budget(name: str, default: int | None) -> int | None:
    """Unset uses the measured default; blank or "none" removes the bound."""
    value = os.getenv(name)
    if value is None:
        return default
    return None if value.strip().lower() in {"", "none"} else int(value)


# Planner reasoning budgets (vLLM thinking_token_budget). Choosing problems
# from the catalog needs far less deliberation than writing a typed plan.
ROUTE_THINKING_TOKEN_BUDGET = 384
PLAN_THINKING_TOKEN_BUDGET = None


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated process configuration loaded from environment variables."""

    repository_root: Path
    data_root: Path
    graphmine_binary: Path
    catalog_path: Path
    manifest_path: Path
    program_instructions_path: Path
    graph_schema_path: Path
    api_host: str
    api_port: int
    api_token: str | None
    allowed_origins: tuple[str, ...]
    graph_gpu_uuid: str | None
    llm_gpu_uuid: str | None
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_enabled: bool
    max_upload_bytes: int | None
    job_timeout_seconds: int | None
    result_summary_items: int
    llm_route_reasoning_effort: str = "none"
    llm_plan_reasoning_effort: str = "medium"
    llm_analyst_reasoning_effort: str = "medium"
    llm_route_max_tokens: int = 768
    llm_plan_max_tokens: int = 3072
    llm_analyst_max_tokens: int = 3072
    llm_sleep_mode: bool = True
    llm_sleep_level: int = 1
    llm_idle_sleep_minutes: float = 20
    llm_thinking_stages: tuple[str, ...] | None = None
    history_directory: Path | None = None
    # Write-once training captures; they outlive conversation deletion.
    capture_directory: Path | None = None
    capture_enabled: bool = True
    map_tile_url: str | None = None
    map_attribution: str = ""
    llm_route_base_url: str | None = None
    llm_route_model: str = "graphmine-business-v1"
    llm_route_adapter_sha256: str | None = None
    llm_route_allow_expanded_catalog: bool = False
    deployment_version: str = "base"
    max_concurrent_uploads: int = 2
    max_pending_jobs: int = 64
    max_result_bytes: int | None = None
    llm_planner_model: str | None = None
    llm_analyst_model: str | None = None
    analytics_planner_model: str | None = None
    # Routing and conceptual replies can share a separate adapter/endpoint.
    analytics_router_model: str | None = None
    analytics_router_base_url: str | None = None
    # Writes the chat answer from computed facts; defaults to GRAPHMINE_LLM_MODEL.
    analytics_answer_model: str | None = None
    # Public web retrieval is deferred; enable only for explicit development work.
    google_search_enabled: bool = False
    analytics_reasoning_effort: str = "medium"
    analytics_thinking_token_budget: int | None = PLAN_THINKING_TOKEN_BUDGET
    analytics_route_thinking_token_budget: int | None = ROUTE_THINKING_TOKEN_BUDGET
    allow_shared_gpu: bool = False
    analytics_python: Path | None = None
    analytics_max_input_bytes: int | None = None
    analytics_result_cache_bytes: int = 64 * 1024 * 1024
    analytics_max_exports: int = 2
    native_runtime_binary: Path | None = None
    native_runtime_library: Path | None = None
    # A worktree may use a separately built, verified native checkout.
    runtime_repository_root: Path | None = None
    analytics_direct_plans: bool = True
    analytics_cpu_workers: int = 2
    analytics_gpu_uuids: tuple[str, ...] = ()
    analytics_gpu_headroom_bytes: int = 512 * 1024 * 1024
    analytics_llm_reserve_bytes: int = 0
    accounts_enabled: bool = True
    account_cookie_secure: bool = True
    account_session_seconds: int = 86400
    max_accounts: int = 100
    account_daily_tokens: int = 50000
    server_daily_tokens: int = 1000000
    account_daily_jobs: int = 10
    server_daily_jobs: int = 100
    max_model_calls: int = 2
    llm_max_num_seqs: int = 2
    model_queue_seconds: int = 60
    account_pending_jobs: int = 8
    account_running_jobs: int = 4
    account_user_running_jobs: int = 1
    account_job_seconds: int = DEFAULT_EXECUTION_TIMEOUT_SECONDS
    account_queue_seconds: int = 900
    # Delete conversations after this many days without activity; 0 keeps them.
    retention_days: int = 0
    admin_event_retention_days: int = 180
    # Online snapshots every backup_hours into this directory, keeping backup_keep.
    backup_directory: Path | None = None
    backup_hours: int = 24
    backup_keep: int = 14
    perf_confirm_shared_gpu: bool = False
    account_storage_bytes: int = 512 * 1024 * 1024
    account_upload_bytes: int | None = None
    # Serve HTTPS directly when no reverse proxy terminates TLS.
    tls_certfile: Path | None = None
    tls_keyfile: Path | None = None
    connectors_file: Path | None = None
    connector_allowed_origins: tuple[str, ...] = ()
    database_sources_file: Path | None = None
    database_credentials_file: Path | None = None
    # A curated deployment exposes only these dataset IDs; empty keeps the
    # general connection/import workspace available for other installations.
    database_dataset_allowlist: tuple[str, ...] = ()
    database_pool_limit: int = 16
    database_pool_size: int = 4
    database_pool_wait_seconds: int = 10
    database_pool_idle_seconds: int = 300
    benchmark_datasets_root: Path | None = None
    neo4j_datasets_registry: Path | None = None
    neo4j_instances_root: Path | None = None
    neo4j_datasets_password_file: Path | None = None
    iu_neo4j_autowake: bool = False
    iu_neo4j_idle_minutes: int = 30
    iu_neo4j_state_dir: Path | None = None
    backend_data_dir: Path = Path.home() / ".local/state/graphmine/backend-runs"
    backend_model_dir: Path = Path.home() / ".local/state/graphmine/backend-models"
    backend_selection: str = "native"
    backend_require_rollout_evidence: bool = True
    backend_exploration_enabled: bool = True
    backend_exploration_budget: float = 0.10
    backend_temperature: float = 1.0
    backend_exploration_floor: float = 0.02
    backend_ipw_clip: float = 20.0
    backend_failure_penalty: float = 10.0
    backend_memory_safety: float = 0.8
    backend_default_timeout_seconds: float = DEFAULT_EXECUTION_TIMEOUT_SECONDS

    @property
    def dual_adapters_active(self) -> bool:
        return bool(self.llm_planner_model and self.llm_analyst_model)

    @property
    def routing_contract_version(self) -> str:
        catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        return catalog.get("routing", {}).get("contract_version", "legacy-20")

    @property
    def routing_adapter_active(self) -> bool:
        return bool(
            self.llm_route_base_url
            and not self.dual_adapters_active
            and (
                self.routing_contract_version == "legacy-20"
                or self.llm_route_allow_expanded_catalog
            )
        )

    @property
    def routing_adapter_experimental(self) -> bool:
        return (
            self.routing_adapter_active and self.routing_contract_version != "legacy-20"
        )

    @property
    def active_routing_model(self) -> str:
        if self.llm_planner_model:
            return self.llm_planner_model
        return self.llm_route_model if self.routing_adapter_active else self.llm_model

    def __post_init__(self) -> None:
        if self.llm_thinking_stages is not None and set(self.llm_thinking_stages) - {"family", "topic", "route", "clarify", "analyst", "plan", "candidates"}:
            raise ValueError("Unknown GRAPHMINE_LLM_THINKING_STAGES value")
        if self.llm_sleep_level != 1:
            raise ValueError("GRAPHMINE_LLM_SLEEP_LEVEL supports only level 1")
        if not 0 < self.llm_idle_sleep_minutes < float("inf"):
            raise ValueError("GRAPHMINE_LLM_IDLE_SLEEP_MINUTES must be a finite positive number")
        if self.backend_selection not in {"native", "shadow", "bandit"}:
            raise ValueError("backend_selection must be native, shadow or bandit")
        if not 0 <= self.backend_exploration_budget <= 1:
            raise ValueError("backend_exploration_budget must be between 0 and 1")
        if not 0 < self.backend_memory_safety <= 0.8:
            raise ValueError("Invalid backend memory safety")
        if not 0 <= self.backend_exploration_floor <= 1 or not 0 < self.backend_temperature < float("inf"):
            raise ValueError("Invalid shared-policy exploration controls")
        if not 1 <= self.backend_ipw_clip < float("inf") or not 1 < self.backend_failure_penalty < float("inf"):
            raise ValueError("Invalid shared-policy training controls")
        if not 0 < self.backend_default_timeout_seconds < float("inf"):
            raise ValueError("Invalid backend attempt timeout")
        for name, maximum in (("database_pool_limit", 128), ("database_pool_size", 32),
                              ("database_pool_wait_seconds", 120), ("database_pool_idle_seconds", 3600)):
            if not 1 <= getattr(self, name) <= maximum:
                raise ValueError(f"{name} must be between 1 and {maximum}")
        if type(self.iu_neo4j_idle_minutes) is not int or self.iu_neo4j_idle_minutes < 1:
            raise ValueError("GRAPHMINE_IU_NEO4J_IDLE_MINUTES must be a positive integer")
        for name in (
            "account_session_seconds",
            "max_accounts",
            "account_daily_tokens",
            "server_daily_tokens",
            "account_daily_jobs",
            "server_daily_jobs",
            "max_model_calls",
            "llm_max_num_seqs",
            "model_queue_seconds",
            "account_pending_jobs",
            "account_running_jobs",
            "account_user_running_jobs",
            "account_job_seconds",
            "account_queue_seconds",
            "account_storage_bytes",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        if bool(self.llm_planner_model) != bool(self.llm_analyst_model):
            raise ValueError(
                "Configure both GRAPHMINE_LLM_PLANNER_MODEL and GRAPHMINE_LLM_ANALYST_MODEL"
            )
        if (
            self.dual_adapters_active
            and self.llm_planner_model == self.llm_analyst_model
        ):
            raise ValueError(
                "Planner and analyst adapters must have distinct model aliases"
            )
        if (
            not self.dual_adapters_active
            and self.llm_route_allow_expanded_catalog
            and not self.llm_route_base_url
        ):
            raise ValueError(
                "Expanded adapter routing requires GRAPHMINE_ROUTER_BASE_URL"
            )
        if self.backup_hours < 1 or self.backup_keep < 1:
            raise ValueError(
                "GRAPHMINE_BACKUP_HOURS and GRAPHMINE_BACKUP_KEEP must be positive"
            )
        if self.backup_directory and self.backup_directory.is_relative_to(
            self.data_root.resolve()
        ):
            raise ValueError("GRAPHMINE_BACKUP_DIR must be outside the data directory")
        if self.retention_days < 0:
            raise ValueError("GRAPHMINE_RETENTION_DAYS cannot be negative")
        if (self.tls_certfile is None) != (self.tls_keyfile is None):
            raise ValueError(
                "Configure both GRAPHMINE_TLS_CERTFILE and GRAPHMINE_TLS_KEYFILE"
            )
        if not 1 <= self.api_port <= 65_535:
            raise ValueError("GRAPHMINE_API_PORT must be between 1 and 65535")
        if self.max_upload_bytes is not None and self.max_upload_bytes < 1:
            raise ValueError("GRAPHMINE_MAX_UPLOAD_BYTES must be positive")
        if self.max_concurrent_uploads < 1:
            raise ValueError("GRAPHMINE_MAX_CONCURRENT_UPLOADS must be positive")
        if self.max_pending_jobs < 1:
            raise ValueError("GRAPHMINE_MAX_PENDING_JOBS must be positive")
        if self.max_result_bytes is not None and self.max_result_bytes < 1:
            raise ValueError("GRAPHMINE_MAX_RESULT_BYTES must be positive")
        if self.account_upload_bytes is not None and self.account_upload_bytes < 1:
            raise ValueError("GRAPHMINE_ACCOUNT_UPLOAD_BYTES must be positive")
        if self.analytics_max_input_bytes is not None and self.analytics_max_input_bytes < 1:
            raise ValueError("GRAPHMINE_ANALYTICS_MAX_INPUT_BYTES must be positive")
        if type(self.analytics_result_cache_bytes) is not int or self.analytics_result_cache_bytes < 0:
            raise ValueError("GRAPHMINE_ANALYTICS_RESULT_CACHE_BYTES must be nonnegative")
        if type(self.analytics_max_exports) is not int or not 1 <= self.analytics_max_exports <= 32:
            raise ValueError("GRAPHMINE_ANALYTICS_MAX_EXPORTS must be between 1 and 32")
        if self.analytics_cpu_workers < 1:
            raise ValueError("GRAPHMINE_ANALYTICS_CPU_WORKERS must be positive")
        for name, budget in (
            ("GRAPHMINE_ANALYTICS_THINKING_TOKEN_BUDGET", self.analytics_thinking_token_budget),
            ("GRAPHMINE_ANALYTICS_ROUTE_THINKING_TOKEN_BUDGET", self.analytics_route_thinking_token_budget),
        ):
            if budget is not None and (
                type(budget) is not int or not 0 <= budget < self.llm_plan_max_tokens
            ):
                raise ValueError(
                    f"{name} must be a nonnegative integer smaller than "
                    "GRAPHMINE_LLM_PLAN_MAX_TOKENS"
                )
        if min(self.analytics_gpu_headroom_bytes, self.analytics_llm_reserve_bytes) < 0:
            raise ValueError("Analytics memory reservations must be nonnegative")
        if self.job_timeout_seconds is not None and self.job_timeout_seconds < 1:
            raise ValueError("GRAPHMINE_JOB_TIMEOUT_SECONDS must be positive")
        if self.result_summary_items < 1:
            raise ValueError("GRAPHMINE_RESULT_SUMMARY_ITEMS must be positive")
        efforts = {
            self.llm_route_reasoning_effort,
            self.llm_plan_reasoning_effort,
            self.llm_analyst_reasoning_effort,
            self.analytics_reasoning_effort,
        }
        if not efforts <= {"none", "low", "medium", "xhigh"}:
            raise ValueError(
                "Qwen reasoning effort must be one of: none, low, medium, xhigh"
            )
        if (
            min(
                self.llm_route_max_tokens,
                self.llm_plan_max_tokens,
                self.llm_analyst_max_tokens,
            )
            < 1
        ):
            raise ValueError("LLM completion-token limits must be positive")
        if (
            self.graph_gpu_uuid
            and self.llm_gpu_uuid
            and self.graph_gpu_uuid == self.llm_gpu_uuid
            and not self.allow_shared_gpu
        ):
            raise ValueError(
                "the LLM and GraphMine processes must use different GPUs unless "
                "GRAPHMINE_ALLOW_SHARED_GPU is enabled with memory reserved for native jobs"
            )

    @classmethod
    def from_env(cls, repository_root: Path | None = None) -> Settings:
        root = (repository_root or Path(__file__).resolve().parents[2]).resolve()
        runtime_root = Path(os.getenv("GRAPHMINE_RUNTIME_REPOSITORY", str(root))).expanduser().resolve()
        data_root = Path(
            os.getenv("GRAPHMINE_AGENT_DATA_ROOT", str(root / ".graphmine-agent"))
        ).resolve()
        origins = tuple(
            item.strip()
            for item in os.getenv(
                "GRAPHMINE_ALLOWED_ORIGINS",
                "http://localhost:8000,http://127.0.0.1:8000",
            ).split(",")
            if item.strip()
        )
        import hashlib
        backend_root = data_root if root not in data_root.parents and data_root != root else (
            Path.home() / ".local/state/graphmine" / hashlib.sha256(str(root).encode()).hexdigest()[:12])
        token = os.getenv("GRAPHMINE_API_TOKEN", "").strip() or None
        return cls(
            llm_thinking_stages=tuple(x.strip() for x in os.environ["GRAPHMINE_LLM_THINKING_STAGES"].split(",") if x.strip())
            if "GRAPHMINE_LLM_THINKING_STAGES" in os.environ else None,
            backend_data_dir=Path(os.getenv("GRAPHMINE_BACKEND_DATA_DIR", str(backend_root / "backend-runs"))).expanduser().resolve(),
            backend_model_dir=Path(os.getenv("GRAPHMINE_BACKEND_MODEL_DIR", str(backend_root / "backend-models"))).expanduser().resolve(),
            backend_selection=os.getenv("GRAPHMINE_BACKEND_SELECTION", "native"),
            backend_require_rollout_evidence=_boolean("GRAPHMINE_BACKEND_REQUIRE_ROLLOUT_EVIDENCE", True),
            backend_exploration_enabled=_boolean("GRAPHMINE_BACKEND_EXPLORATION_ENABLED", True),
            backend_exploration_budget=float(os.getenv("GRAPHMINE_BACKEND_EXPLORATION_BUDGET", "0.10")),
            backend_temperature=float(os.getenv("GRAPHMINE_BACKEND_TEMPERATURE", "1.0")),
            backend_exploration_floor=float(os.getenv("GRAPHMINE_BACKEND_EXPLORATION_FLOOR", "0.02")),
            backend_ipw_clip=float(os.getenv("GRAPHMINE_BACKEND_IPW_CLIP", "20")),
            backend_failure_penalty=float(os.getenv("GRAPHMINE_BACKEND_FAILURE_PENALTY", "10")),
            backend_memory_safety=float(os.getenv("GRAPHMINE_BACKEND_MEMORY_SAFETY", "0.8")),
            backend_default_timeout_seconds=float(os.getenv("GRAPHMINE_BACKEND_DEFAULT_TIMEOUT_SECONDS", str(DEFAULT_EXECUTION_TIMEOUT_SECONDS))),
            database_credentials_file=Path(os.environ["GRAPHMINE_DATABASE_CREDENTIALS_FILE"]).expanduser().absolute()
            if os.getenv("GRAPHMINE_DATABASE_CREDENTIALS_FILE") else None,
            database_dataset_allowlist=tuple(
                item.strip() for item in os.getenv("GRAPHMINE_DATABASE_DATASET_ALLOWLIST", "").split(",") if item.strip()
            ),
            neo4j_datasets_registry=Path(os.environ["GRAPHMINE_NEO4J_DATASETS_REGISTRY"]).expanduser().resolve()
            if os.getenv("GRAPHMINE_NEO4J_DATASETS_REGISTRY") else None,
            neo4j_instances_root=Path(os.environ["GRAPHMINE_NEO4J_INSTANCES_ROOT"]).expanduser().resolve()
            if os.getenv("GRAPHMINE_NEO4J_INSTANCES_ROOT") else None,
            neo4j_datasets_password_file=Path(os.environ["GRAPHMINE_NEO4J_DATASETS_PASSWORD_FILE"]).expanduser().absolute()
            if os.getenv("GRAPHMINE_NEO4J_DATASETS_PASSWORD_FILE") else None,
            iu_neo4j_autowake=_boolean("GRAPHMINE_IU_NEO4J_AUTOWAKE", False),
            iu_neo4j_idle_minutes=_integer("GRAPHMINE_IU_NEO4J_IDLE_MINUTES", 30),
            iu_neo4j_state_dir=Path(os.environ["GRAPHMINE_IU_NEO4J_STATE_DIR"]).expanduser().absolute()
            if os.getenv("GRAPHMINE_IU_NEO4J_STATE_DIR") else None,
            benchmark_datasets_root=Path(os.environ["GRAPHMINE_BENCHMARK_DATASETS_ROOT"])
            .expanduser().resolve()
            if os.getenv("GRAPHMINE_BENCHMARK_DATASETS_ROOT") else None,
            database_sources_file=Path(os.environ["GRAPHMINE_DATABASE_SOURCES_FILE"])
            .expanduser().resolve()
            if os.getenv("GRAPHMINE_DATABASE_SOURCES_FILE") else None,
            connector_allowed_origins=tuple(
                origin.strip().rstrip("/")
                for origin in os.getenv(
                    "GRAPHMINE_CONNECTOR_ALLOWED_ORIGINS", ""
                ).split(",")
                if origin.strip()
            ),
            connectors_file=Path(os.environ["GRAPHMINE_CONNECTORS_FILE"])
            .expanduser()
            .resolve()
            if os.getenv("GRAPHMINE_CONNECTORS_FILE")
            else None,
            accounts_enabled=_boolean("GRAPHMINE_ACCOUNTS_ENABLED", True),
            account_cookie_secure=_boolean("GRAPHMINE_ACCOUNT_COOKIE_SECURE", True),
            account_session_seconds=_integer(
                "GRAPHMINE_ACCOUNT_SESSION_SECONDS", 86400
            ),
            max_accounts=_integer("GRAPHMINE_MAX_ACCOUNTS", 100),
            account_daily_tokens=_integer("GRAPHMINE_ACCOUNT_DAILY_TOKENS", 50000),
            server_daily_tokens=_integer("GRAPHMINE_SERVER_DAILY_TOKENS", 1000000),
            account_daily_jobs=_integer("GRAPHMINE_ACCOUNT_DAILY_JOBS", 10),
            server_daily_jobs=_integer("GRAPHMINE_SERVER_DAILY_JOBS", 100),
            max_model_calls=_integer("GRAPHMINE_MAX_MODEL_CALLS", 2),
            llm_max_num_seqs=_integer("GRAPHMINE_LLM_MAX_NUM_SEQS", 2),
            model_queue_seconds=_integer("GRAPHMINE_MODEL_QUEUE_SECONDS", _integer("MODEL_QUEUE_SECONDS", 60)),
            account_pending_jobs=_integer("GRAPHMINE_ACCOUNT_PENDING_JOBS", 8),
            account_running_jobs=_integer("GRAPHMINE_ACCOUNT_RUNNING_JOBS", 4),
            account_user_running_jobs=_integer("GRAPHMINE_ACCOUNT_USER_RUNNING_JOBS", 1),
            account_job_seconds=_integer("GRAPHMINE_ACCOUNT_JOB_SECONDS", DEFAULT_EXECUTION_TIMEOUT_SECONDS),
            account_queue_seconds=_integer("GRAPHMINE_ACCOUNT_QUEUE_SECONDS", 900),
            retention_days=_integer("GRAPHMINE_RETENTION_DAYS", 0),
            admin_event_retention_days=max(1, _integer("GRAPHMINE_ADMIN_EVENT_RETENTION_DAYS", 180)),
            backup_directory=Path(os.environ["GRAPHMINE_BACKUP_DIR"])
            .expanduser()
            .resolve()
            if os.getenv("GRAPHMINE_BACKUP_DIR")
            else None,
            backup_hours=_integer("GRAPHMINE_BACKUP_HOURS", 24),
            backup_keep=_integer("GRAPHMINE_BACKUP_KEEP", 14),
            perf_confirm_shared_gpu=_boolean("GRAPHMINE_PERF_CONFIRM_SHARED_GPU", False),
            account_storage_bytes=_integer(
                "GRAPHMINE_ACCOUNT_STORAGE_BYTES", 512 * 1024 * 1024
            ),
            account_upload_bytes=_budget(
                "GRAPHMINE_ACCOUNT_UPLOAD_BYTES", None
            ),
            tls_certfile=Path(os.environ["GRAPHMINE_TLS_CERTFILE"])
            .expanduser()
            .resolve()
            if os.getenv("GRAPHMINE_TLS_CERTFILE")
            else None,
            tls_keyfile=Path(os.environ["GRAPHMINE_TLS_KEYFILE"]).expanduser().resolve()
            if os.getenv("GRAPHMINE_TLS_KEYFILE")
            else None,
            repository_root=root,
            runtime_repository_root=runtime_root if os.getenv("GRAPHMINE_RUNTIME_REPOSITORY") else None,
            analytics_direct_plans=_boolean("GRAPHMINE_ANALYTICS_DIRECT_PLANS", True),
            data_root=data_root,
            graphmine_binary=Path(
                os.getenv(
                    "GRAPHMINE_BINARY", str(runtime_root / "library" / "build" / "graphmine")
                )
            ).resolve(),
            native_runtime_binary=Path(
                os.getenv(
                    "GRAPHMINE_NATIVE_BINARY",
                    str(runtime_root / "library/build/runtime/graphmine-native"),
                )
            )
            .expanduser()
            .resolve(),
            native_runtime_library=Path(os.environ["GRAPHMINE_NATIVE_LIBRARY"])
            .expanduser()
            .resolve()
            if os.getenv("GRAPHMINE_NATIVE_LIBRARY")
            else None,
            catalog_path=(root / "graphmine_catalog.json").resolve(),
            manifest_path=(root / "graphmine_manifest.json").resolve(),
            program_instructions_path=(
                root / "agent" / "program_instructions.json"
            ).resolve(),
            graph_schema_path=(root / "problems" / "graph_input.schema.json").resolve(),
            api_host=os.getenv("GRAPHMINE_API_HOST", "0.0.0.0"),
            api_port=_integer("GRAPHMINE_API_PORT", 8000),
            api_token=token,
            allowed_origins=origins,
            graph_gpu_uuid=os.getenv("GRAPHMINE_GRAPH_GPU_UUID", "").strip() or None,
            llm_gpu_uuid=os.getenv("GRAPHMINE_LLM_GPU_UUID", "").strip() or None,
            allow_shared_gpu=_boolean("GRAPHMINE_ALLOW_SHARED_GPU", False),
            analytics_python=Path(os.environ["GRAPHMINE_ANALYTICS_PYTHON"])
            .expanduser()
            # Resolving bin/python's symlink loses its virtual environment.
            .absolute()
            if os.getenv("GRAPHMINE_ANALYTICS_PYTHON")
            else None,
            analytics_max_input_bytes=_budget(
                "GRAPHMINE_ANALYTICS_MAX_INPUT_BYTES", None
            ),
            analytics_cpu_workers=_integer("GRAPHMINE_ANALYTICS_CPU_WORKERS", 2),
            analytics_gpu_uuids=tuple(
                value.strip()
                for value in os.getenv("GRAPHMINE_ANALYTICS_GPU_UUIDS", "").split(",")
                if value.strip()
            ),
            analytics_gpu_headroom_bytes=_integer(
                "GRAPHMINE_ANALYTICS_GPU_HEADROOM_BYTES", 512 * 1024 * 1024
            ),
            analytics_llm_reserve_bytes=_integer(
                "GRAPHMINE_ANALYTICS_LLM_RESERVE_BYTES", 0
            ),
            llm_base_url=os.getenv(
                "GRAPHMINE_LLM_BASE_URL", "http://127.0.0.1:8001/v1"
            ).rstrip("/"),
            llm_api_key=os.getenv("GRAPHMINE_LLM_API_KEY", "local-graphmine"),
            llm_model=os.getenv("GRAPHMINE_LLM_MODEL", "Qwen/Qwen3.8-27B-FP8"),
            llm_enabled=_boolean("GRAPHMINE_LLM_ENABLED", True),
            llm_sleep_mode=_boolean("GRAPHMINE_LLM_SLEEP_MODE", True),
            llm_sleep_level=_integer("GRAPHMINE_LLM_SLEEP_LEVEL", 1),
            llm_idle_sleep_minutes=float(os.getenv("GRAPHMINE_LLM_IDLE_SLEEP_MINUTES", "20")),
            google_search_enabled=_boolean("GRAPHMINE_GOOGLE_SEARCH_ENABLED", False),
            llm_planner_model=os.getenv("GRAPHMINE_LLM_PLANNER_MODEL", "").strip()
            or None,
            llm_analyst_model=os.getenv("GRAPHMINE_LLM_ANALYST_MODEL", "").strip()
            or None,
            analytics_planner_model=os.getenv(
                "GRAPHMINE_ANALYTICS_PLANNER_MODEL", ""
            ).strip()
            or None,
            analytics_router_model=os.getenv("GRAPHMINE_ANALYTICS_ROUTER_MODEL", "").strip() or None,
            analytics_router_base_url=os.getenv("GRAPHMINE_ANALYTICS_ROUTER_BASE_URL", "").strip().rstrip("/") or None,
            analytics_reasoning_effort=os.getenv(
                "GRAPHMINE_ANALYTICS_REASONING_EFFORT", "medium"
            ),
            analytics_answer_model=os.getenv(
                "GRAPHMINE_ANALYTICS_ANSWER_MODEL", ""
            ).strip()
            or None,
            analytics_thinking_token_budget=_budget(
                "GRAPHMINE_ANALYTICS_THINKING_TOKEN_BUDGET", PLAN_THINKING_TOKEN_BUDGET
            ),
            analytics_route_thinking_token_budget=_budget(
                "GRAPHMINE_ANALYTICS_ROUTE_THINKING_TOKEN_BUDGET",
                ROUTE_THINKING_TOKEN_BUDGET,
            ),
            max_upload_bytes=_budget("GRAPHMINE_MAX_UPLOAD_BYTES", None),
            max_concurrent_uploads=_integer("GRAPHMINE_MAX_CONCURRENT_UPLOADS", 2),
            database_pool_limit=_integer("GRAPHMINE_DATABASE_POOL_LIMIT", 16),
            database_pool_size=_integer("GRAPHMINE_DATABASE_POOL_SIZE", 4),
            database_pool_wait_seconds=_integer("GRAPHMINE_DATABASE_POOL_WAIT_SECONDS", 10),
            database_pool_idle_seconds=_integer("GRAPHMINE_DATABASE_POOL_IDLE_SECONDS", 300),
            max_pending_jobs=_integer("GRAPHMINE_MAX_PENDING_JOBS", 64),
            max_result_bytes=_budget("GRAPHMINE_MAX_RESULT_BYTES", None),
            analytics_result_cache_bytes=_integer("GRAPHMINE_ANALYTICS_RESULT_CACHE_BYTES", 64 * 1024 * 1024),
            analytics_max_exports=_integer("GRAPHMINE_ANALYTICS_MAX_EXPORTS", 2),
            job_timeout_seconds=_budget("GRAPHMINE_JOB_TIMEOUT_SECONDS", DEFAULT_EXECUTION_TIMEOUT_SECONDS),
            result_summary_items=_integer("GRAPHMINE_RESULT_SUMMARY_ITEMS", 50),
            llm_route_reasoning_effort=os.getenv(
                "GRAPHMINE_LLM_ROUTE_REASONING_EFFORT", "none"
            ),
            llm_plan_reasoning_effort=os.getenv(
                "GRAPHMINE_LLM_PLAN_REASONING_EFFORT", "medium"
            ),
            llm_analyst_reasoning_effort=os.getenv(
                "GRAPHMINE_LLM_ANALYST_REASONING_EFFORT", "medium"
            ),
            llm_route_max_tokens=_integer("GRAPHMINE_LLM_ROUTE_MAX_TOKENS", 768),
            llm_plan_max_tokens=_integer("GRAPHMINE_LLM_PLAN_MAX_TOKENS", 3072),
            llm_analyst_max_tokens=_integer("GRAPHMINE_LLM_ANALYST_MAX_TOKENS", 3072),
            history_directory=(
                Path(os.environ["GRAPHMINE_HISTORY_ROOT"]).expanduser().resolve()
                if os.getenv("GRAPHMINE_HISTORY_ROOT")
                else None
            ),
            capture_directory=(
                Path(os.environ["GRAPHMINE_CAPTURE_ROOT"]).expanduser().resolve()
                if os.getenv("GRAPHMINE_CAPTURE_ROOT")
                else None
            ),
            capture_enabled=_boolean("GRAPHMINE_CAPTURE_ENABLED", True),
            llm_route_base_url=os.getenv("GRAPHMINE_ROUTER_BASE_URL", "").rstrip("/")
            or None,
            llm_route_model=os.getenv(
                "GRAPHMINE_ROUTER_MODEL", "graphmine-business-v1"
            ),
            llm_route_adapter_sha256=os.getenv("GRAPHMINE_ROUTER_ADAPTER_SHA256")
            or None,
            llm_route_allow_expanded_catalog=_boolean(
                "GRAPHMINE_ROUTER_ALLOW_EXPANDED_CATALOG", False
            ),
            deployment_version=os.getenv("GRAPHMINE_DEPLOYMENT_VERSION", "base"),
            map_tile_url=os.getenv("GRAPHMINE_MAP_TILE_URL") or None,
            map_attribution=os.getenv("GRAPHMINE_MAP_ATTRIBUTION", ""),
        )

    @property
    def native_repository_root(self) -> Path:
        return self.runtime_repository_root or self.repository_root

    @property
    def database_path(self) -> Path:
        return self.data_root / "agent.sqlite3"

    @property
    def workspaces_root(self) -> Path:
        return self.data_root / "jobs"

    @property
    def history_root(self) -> Path:
        return self.history_directory or self.data_root / "history"

    @property
    def capture_root(self) -> Path:
        return self.capture_directory or self.data_root / "captures"
