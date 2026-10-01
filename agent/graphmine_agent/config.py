from __future__ import annotations

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

    def __post_init__(self) -> None:
        if not 1 <= self.api_port <= 65_535:
            raise ValueError("GRAPHMINE_API_PORT must be between 1 and 65535")
        if self.max_upload_bytes < 1:
            raise ValueError("GRAPHMINE_MAX_UPLOAD_BYTES must be positive")
        if self.job_timeout_seconds < 1:
            raise ValueError("GRAPHMINE_JOB_TIMEOUT_SECONDS must be positive")
        if self.result_summary_items < 1:
            raise ValueError("GRAPHMINE_RESULT_SUMMARY_ITEMS must be positive")
        efforts = {
            self.llm_route_reasoning_effort,
            self.llm_plan_reasoning_effort,
            self.llm_analyst_reasoning_effort,
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
        ):
            raise ValueError("the LLM and GraphMine processes must use different GPUs")

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
            repository_root=root,
            data_root=data_root,
            graphmine_binary=Path(
                os.getenv(
                    "GRAPHMINE_BINARY", str(root / "library" / "build" / "graphmine")
                )
            ).resolve(),
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
            llm_base_url=os.getenv(
                "GRAPHMINE_LLM_BASE_URL", "http://127.0.0.1:8001/v1"
            ).rstrip("/"),
            llm_api_key=os.getenv("GRAPHMINE_LLM_API_KEY", "local-graphmine"),
            llm_model=os.getenv("GRAPHMINE_LLM_MODEL", "Qwen/Qwen3.8-27B-FP8"),
            llm_enabled=_boolean("GRAPHMINE_LLM_ENABLED", True),
            max_upload_bytes=_integer("GRAPHMINE_MAX_UPLOAD_BYTES", 2_147_483_648),
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
        )

    @property
    def database_path(self) -> Path:
        return self.data_root / "agent.sqlite3"

    @property
    def workspaces_root(self) -> Path:
        return self.data_root / "jobs"
