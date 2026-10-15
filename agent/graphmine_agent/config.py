from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _integer(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


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
    backend_policy_path: Path
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
    max_upload_bytes: int
    job_timeout_seconds: int
    result_summary_items: int
    llm_route_reasoning_effort: str = "none"
    llm_plan_reasoning_effort: str = "medium"
    llm_analyst_reasoning_effort: str = "medium"
    llm_route_max_tokens: int = 768
    llm_plan_max_tokens: int = 3072
    llm_analyst_max_tokens: int = 3072
    history_directory: Path | None = None
    llm_route_base_url: str | None = None
    llm_route_model: str = "graphmine-business-v1"
    llm_route_adapter_sha256: str | None = None
    llm_route_allow_expanded_catalog: bool = False
    deployment_version: str = "base"
    max_concurrent_uploads: int = 2
    max_pending_jobs: int = 64
    max_result_bytes: int = 64 * 1024 * 1024
    llm_planner_model: str | None = None
    llm_analyst_model: str | None = None
    analytics_planner_model: str | None = None
    # Writes the chat answer from computed facts; defaults to GRAPHMINE_LLM_MODEL.
    analytics_answer_model: str | None = None
    analytics_reasoning_effort: str = "medium"
    analytics_thinking_token_budget: int | None = None
    allow_shared_gpu: bool = False
    analytics_python: Path | None = None
    analytics_max_input_bytes: int = 64 * 1024 * 1024
    native_runtime_binary: Path | None = None
    native_runtime_library: Path | None = None
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
    account_pending_jobs: int = 8
    account_running_jobs: int = 4
    account_job_seconds: int = 300
    account_queue_seconds: int = 900
    # Delete conversations after this many days without activity; 0 keeps them.
    retention_days: int = 0
    # Online snapshots every backup_hours into this directory, keeping backup_keep.
    backup_directory: Path | None = None
    backup_hours: int = 24
    backup_keep: int = 7
    account_storage_bytes: int = 512 * 1024 * 1024
    account_upload_bytes: int = 64 * 1024 * 1024
    # Serve HTTPS directly when no reverse proxy terminates TLS.
    tls_certfile: Path | None = None
    tls_keyfile: Path | None = None
    connectors_file: Path | None = None
    connector_allowed_origins: tuple[str, ...] = ()

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
        for name in (
            "account_session_seconds",
            "max_accounts",
            "account_daily_tokens",
            "server_daily_tokens",
            "account_daily_jobs",
            "server_daily_jobs",
            "max_model_calls",
            "account_pending_jobs",
            "account_running_jobs",
            "account_job_seconds",
            "account_queue_seconds",
            "account_storage_bytes",
            "account_upload_bytes",
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
        if self.max_upload_bytes < 1:
            raise ValueError("GRAPHMINE_MAX_UPLOAD_BYTES must be positive")
        if self.max_concurrent_uploads < 1:
            raise ValueError("GRAPHMINE_MAX_CONCURRENT_UPLOADS must be positive")
        if self.max_pending_jobs < 1:
            raise ValueError("GRAPHMINE_MAX_PENDING_JOBS must be positive")
        if self.max_result_bytes < 1:
            raise ValueError("GRAPHMINE_MAX_RESULT_BYTES must be positive")
        if self.analytics_max_input_bytes < 1:
            raise ValueError("GRAPHMINE_ANALYTICS_MAX_INPUT_BYTES must be positive")
        if self.analytics_cpu_workers < 1:
            raise ValueError("GRAPHMINE_ANALYTICS_CPU_WORKERS must be positive")
        if self.analytics_thinking_token_budget is not None and (
            type(self.analytics_thinking_token_budget) is not int
            or not 0 <= self.analytics_thinking_token_budget < self.llm_plan_max_tokens
        ):
            raise ValueError(
                "GRAPHMINE_ANALYTICS_THINKING_TOKEN_BUDGET must be a nonnegative "
                "integer smaller than GRAPHMINE_LLM_PLAN_MAX_TOKENS"
            )
        if min(self.analytics_gpu_headroom_bytes, self.analytics_llm_reserve_bytes) < 0:
            raise ValueError("Analytics memory reservations must be nonnegative")
        if self.job_timeout_seconds < 1:
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
        token = os.getenv("GRAPHMINE_API_TOKEN", "").strip() or None
        return cls(
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
            account_pending_jobs=_integer("GRAPHMINE_ACCOUNT_PENDING_JOBS", 8),
            account_running_jobs=_integer("GRAPHMINE_ACCOUNT_RUNNING_JOBS", 4),
            account_job_seconds=_integer("GRAPHMINE_ACCOUNT_JOB_SECONDS", 300),
            account_queue_seconds=_integer("GRAPHMINE_ACCOUNT_QUEUE_SECONDS", 900),
            retention_days=_integer("GRAPHMINE_RETENTION_DAYS", 0),
            backup_directory=Path(os.environ["GRAPHMINE_BACKUP_DIR"])
            .expanduser()
            .resolve()
            if os.getenv("GRAPHMINE_BACKUP_DIR")
            else None,
            backup_hours=_integer("GRAPHMINE_BACKUP_HOURS", 24),
            backup_keep=_integer("GRAPHMINE_BACKUP_KEEP", 7),
            account_storage_bytes=_integer(
                "GRAPHMINE_ACCOUNT_STORAGE_BYTES", 512 * 1024 * 1024
            ),
            account_upload_bytes=_integer(
                "GRAPHMINE_ACCOUNT_UPLOAD_BYTES", 64 * 1024 * 1024
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
            data_root=data_root,
            graphmine_binary=Path(
                os.getenv(
                    "GRAPHMINE_BINARY", str(root / "library" / "build" / "graphmine")
                )
            ).resolve(),
            native_runtime_binary=Path(
                os.getenv(
                    "GRAPHMINE_NATIVE_BINARY",
                    str(root / "library/build/runtime/graphmine-native"),
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
            backend_policy_path=Path(
                os.getenv(
                    "GRAPHMINE_BACKEND_POLICY",
                    str(root / "agent" / "backend_policy.json"),
                )
            ).resolve(),
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
            analytics_max_input_bytes=_integer(
                "GRAPHMINE_ANALYTICS_MAX_INPUT_BYTES", 64 * 1024 * 1024
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
            llm_planner_model=os.getenv("GRAPHMINE_LLM_PLANNER_MODEL", "").strip()
            or None,
            llm_analyst_model=os.getenv("GRAPHMINE_LLM_ANALYST_MODEL", "").strip()
            or None,
            analytics_planner_model=os.getenv(
                "GRAPHMINE_ANALYTICS_PLANNER_MODEL", ""
            ).strip()
            or None,
            analytics_reasoning_effort=os.getenv(
                "GRAPHMINE_ANALYTICS_REASONING_EFFORT", "medium"
            ),
            analytics_answer_model=os.getenv(
                "GRAPHMINE_ANALYTICS_ANSWER_MODEL", ""
            ).strip()
            or None,
            analytics_thinking_token_budget=_integer(
                "GRAPHMINE_ANALYTICS_THINKING_TOKEN_BUDGET", 0
            )
            if os.getenv("GRAPHMINE_ANALYTICS_THINKING_TOKEN_BUDGET", "").strip()
            else None,
            max_upload_bytes=_integer("GRAPHMINE_MAX_UPLOAD_BYTES", 2_147_483_648),
            max_concurrent_uploads=_integer("GRAPHMINE_MAX_CONCURRENT_UPLOADS", 2),
            max_pending_jobs=_integer("GRAPHMINE_MAX_PENDING_JOBS", 64),
            max_result_bytes=_integer("GRAPHMINE_MAX_RESULT_BYTES", 64 * 1024 * 1024),
            job_timeout_seconds=_integer("GRAPHMINE_JOB_TIMEOUT_SECONDS", 86_400),
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
        )

    @property
    def database_path(self) -> Path:
        return self.data_root / "agent.sqlite3"

    @property
    def workspaces_root(self) -> Path:
        return self.data_root / "jobs"

    @property
    def history_root(self) -> Path:
        return self.history_directory or self.data_root / "history"
