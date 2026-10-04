from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from . import __version__
from .catalog import Catalog
from .config import Settings
from .graph_store import GraphStore, UploadError
from .history import HistoryStore
from .models import CapabilityReport, ExecutionPlan, FileRole
from .planning import PlanValidator
from .profiles import EXPANSION_OPERATIONS, ProfileInputError, prepare_operation_graph
from .selector import CORRECTNESS_EXCLUSIONS, BackendSelector


class ExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, exit_code: int | None = None):
        self.code = code
        self.exit_code = exit_code
        super().__init__(message)


class GraphMineRunner:
    """Only component permitted to construct and execute GraphMine commands."""

    def __init__(
        self,
        settings: Settings,
        catalog: Catalog,
        graph_store: GraphStore,
        validator: PlanValidator,
    ):
        self.settings = settings
        self.catalog = catalog
        self.graph_store = graph_store
        self.validator = validator
        self.selector = BackendSelector(
            settings.backend_policy_path, catalog, validator
        )
        self._capabilities: CapabilityReport | None = None

    def probe(self) -> CapabilityReport:
        binary = self.settings.graphmine_binary
        if not binary.is_file() or not os.access(binary, os.X_OK):
            report = CapabilityReport(
                binary_available=False,
                binary_path=str(binary),
                library_version=None,
                graph_gpu_uuid=self.settings.graph_gpu_uuid,
                operation_count=len(self.catalog.instructions),
                validated_backend_count=sum(
                    len(op["backends"])
                    for op in self.catalog.manifest_operations.values()
                ),
                compiled_backend_count=0,
                operations=[],
                error="GraphMine binary is missing or not executable",
                backend_policy_path=str(self.selector.path),
                backend_policy_loaded=self.selector.loaded,
                backend_policy_error=self.selector.error,
                backend_correctness_exclusions=CORRECTNESS_EXCLUSIONS,
            )
            self._capabilities = report
            return report
        environment = self._environment()
        try:
            completed = subprocess.run(
                [str(binary), "list", "--pretty"],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                env=environment,
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or "graphmine list failed")
            value = json.loads(completed.stdout)
            library_version = (
                str(value["library_version"])
                if value.get("library_version") is not None
                else None
            )
            report = CapabilityReport(
                binary_available=True,
                binary_path=str(binary),
                library_version=library_version,
                graph_gpu_uuid=self.settings.graph_gpu_uuid,
                operation_count=int(value["operation_count"]),
                validated_backend_count=int(value["validated_backend_count"]),
                compiled_backend_count=int(value["compiled_backend_count"]),
                operations=list(value["operations"]),
                error=(
                    None
                    if library_version == __version__
                    else (
                        "GraphMine binary version "
                        f"{library_version or 'unknown'} does not match agent "
                        f"version {__version__}"
                    )
                ),
                backend_policy_path=str(self.selector.path),
                backend_policy_loaded=self.selector.loaded,
                backend_policy_error=self.selector.error,
                backend_correctness_exclusions=CORRECTNESS_EXCLUSIONS,
            )
        except (
            OSError,
            subprocess.SubprocessError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            report = CapabilityReport(
                binary_available=True,
                binary_path=str(binary),
                library_version=None,
                graph_gpu_uuid=self.settings.graph_gpu_uuid,
                operation_count=len(self.catalog.instructions),
                validated_backend_count=sum(
                    len(op["backends"])
                    for op in self.catalog.manifest_operations.values()
                ),
                compiled_backend_count=0,
                operations=[],
                error=str(error),
                backend_policy_path=str(self.selector.path),
                backend_policy_loaded=self.selector.loaded,
                backend_policy_error=self.selector.error,
                backend_correctness_exclusions=CORRECTNESS_EXCLUSIONS,
            )
        self._capabilities = report
        return report

    @property
    def capabilities(self) -> CapabilityReport:
        return self._capabilities or self.probe()

    def require_ready(self) -> CapabilityReport:
        capability = self.capabilities
        if not capability.binary_available or capability.error:
            raise ExecutionError(
                (
                    "binary_incompatible"
                    if capability.binary_available
                    else "binary_unavailable"
                ),
                capability.error or "GraphMine binary unavailable",
            )
        return capability

    @property
    def compiled_backends(self) -> set[str]:
        result: set[str] = set()
        for operation in self.capabilities.operations:
            for backend in operation.get("backends", []):
                if backend.get("compiled"):
                    result.add(str(backend["id"]))
        return result

    def compiled_backends_for(self, operation_id: str) -> set[str]:
        for operation in self.capabilities.operations:
            if operation.get("id") == operation_id:
                return {
                    str(backend["id"])
                    for backend in operation.get("backends", [])
                    if backend.get("compiled")
                }
        return set()

    def _environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        # Native workers remain in this job's group so cancellation kills them too.
        environment["GRAPHMINE_WORKER_INHERIT_PROCESS_GROUP"] = "1"
        if self.settings.graph_gpu_uuid:
            environment["CUDA_VISIBLE_DEVICES"] = self.settings.graph_gpu_uuid
        return environment

    def build_command(self, plan: ExecutionPlan, result_path: Path) -> list[str]:
        compiled = (
            self.compiled_backends_for(plan.operation_id)
            if self.capabilities.binary_available
            else None
        )
        graph_record = self.graph_store.database.get_file(plan.graph_id)
        if graph_record.role != FileRole.graph:
            raise UploadError("graph_id must identify a main graph file")
        if compiled is not None:
            plan = self.selector.select(plan, graph_record.metadata, compiled)
        plan = self.validator.validate(
            plan, compiled_backends=compiled, for_execution=True
        )
        operation = self.catalog.operation(plan.operation_id)
        graph_path = self.graph_store.execution_path(plan.graph_id, plan.session_id)
        if plan.operation_id in EXPANSION_OPERATIONS or (
            plan.application_intent and plan.application_intent.filters
        ):
            from .graph_context import project_graph

            projected = project_graph(
                self.graph_store.read_graph(plan.graph_id, plan.session_id),
                plan.application_intent.filters if plan.application_intent else [],
            )
            try:
                projected = prepare_operation_graph(projected, plan)
            except ProfileInputError as error:
                raise ExecutionError(error.status, str(error)) from error
            result_path.parent.mkdir(parents=True, exist_ok=True)
            graph_path = result_path.parent / "projected-graph.json"
            graph_path.write_text(
                json.dumps(projected, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            (result_path.parent / "projection.json").write_text(
                json.dumps(
                    {
                        "source_graph_id": plan.graph_id,
                        "source_sha256": graph_record.sha256,
                        "filters": [
                            item.model_dump()
                            for item in (
                                plan.application_intent.filters
                                if plan.application_intent
                                else []
                            )
                        ],
                        "weight_attribute": plan.application_intent.weight_attribute
                        if plan.application_intent
                        else None,
                        "operation_profile": operation.instruction.get(
                            "validated_profile"
                        ),
                        "vertices": len(projected["vertices"]),
                        "edges": len(projected["edges"]),
                        "isolated_vertices": "retained unless excluded by a vertex filter",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        command = [
            str(self.settings.graphmine_binary),
            "run",
            plan.operation_id,
            "--graph",
            str(graph_path),
            "--backend",
            plan.backend_id,
            "--device",
            "0",
        ]
        if plan.allow_directed_projection:
            command.append("--allow-directed-projection")
        if not plan.collect_statistics:
            command.append("--no-statistics")

        for name, specification in operation.instruction["parameters"].items():
            if name not in plan.parameters:
                continue
            value = plan.parameters[name]
            flag = specification["flag"]
            if specification["type"] == "boolean":
                if value:
                    command.append(flag)
            elif specification["type"] == "vertex_id":
                command.extend([flag, json.dumps(value, ensure_ascii=False)])
            else:
                command.extend([flag, str(value)])

        if plan.operation_id in EXPANSION_OPERATIONS - {"butterfly-counting"}:
            command.extend(
                ["--timeout-seconds", str(min(60, self.settings.job_timeout_seconds))]
            )

        for name, specification in operation.instruction["auxiliary_inputs"].items():
            for file_id in plan.auxiliary_inputs.get(name, []):
                file_record = self.graph_store.database.get_file(file_id)
                if file_record.role.value != specification["role"]:
                    raise UploadError(
                        f"file {file_id} has role {file_record.role.value}, expected {specification['role']}"
                    )
                path = self.graph_store.execution_path(file_id, plan.session_id)
                command.extend([specification["flag"], str(path)])

        emitted_flags: set[str] = set()
        for output in plan.optional_outputs:
            flag = operation.instruction["optional_outputs"][output]
            if flag not in emitted_flags:
                command.append(flag)
                emitted_flags.add(flag)
        command.extend(["--output", str(result_path), "--pretty"])
        return command

    async def execute(
        self, plan: ExecutionPlan, workspace: Path
    ) -> tuple[dict[str, Any], list[str]]:
        workspace = workspace.resolve()
        allowed = self.settings.workspaces_root.resolve()
        if workspace != allowed and allowed not in workspace.parents:
            raise ExecutionError("unsafe_workspace", "job workspace escaped data root")
        self.require_ready()
        workspace.mkdir(parents=True, exist_ok=True)
        result_path = workspace / "result.json"
        stdout_path = workspace / "stdout.log"
        stderr_path = workspace / "stderr.log"
        command = self.build_command(plan, result_path)
        (workspace / "command.json").write_text(
            json.dumps(command, indent=2) + "\n", encoding="utf-8"
        )

        process: asyncio.subprocess.Process | None = None
        started = time.monotonic()
        try:
            with (
                stdout_path.open("wb") as stdout_file,
                stderr_path.open("wb") as stderr_file,
            ):
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd=workspace,
                    env=self._environment(),
                    start_new_session=True,
                )
                try:
                    exit_code = await asyncio.wait_for(
                        process.wait(), timeout=self.settings.job_timeout_seconds
                    )
                except TimeoutError as error:
                    await self._terminate_and_wait(process)
                    HistoryStore.write(
                        workspace / "process.json",
                        {
                            "exit_code": process.returncode,
                            "status": "timeout",
                            "elapsed_seconds": time.monotonic() - started,
                        },
                    )
                    raise ExecutionError(
                        "timeout",
                        f"GraphMine exceeded {self.settings.job_timeout_seconds} seconds",
                    ) from error
        except asyncio.CancelledError:
            if process and process.returncode is None:
                await self._terminate_and_wait(process)
            HistoryStore.write(
                workspace / "process.json",
                {
                    "exit_code": process.returncode if process else None,
                    "status": "cancelled",
                    "elapsed_seconds": time.monotonic() - started,
                },
            )
            raise

        HistoryStore.write(
            workspace / "process.json",
            {
                "exit_code": exit_code,
                "status": "exited",
                "elapsed_seconds": time.monotonic() - started,
            },
        )

        if not result_path.is_file():
            stderr = stderr_path.read_text(encoding="utf-8", errors="replace")[-8_000:]
            raise ExecutionError(
                "missing_result",
                stderr.strip() or "GraphMine did not create result.json",
                exit_code=exit_code,
            )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ExecutionError(
                "invalid_result", f"invalid result JSON: {error}"
            ) from error
        if not isinstance(payload, dict):
            raise ExecutionError(
                "invalid_result", "GraphMine result root is not an object"
            )
        if exit_code not in {0, 3}:
            raise ExecutionError(
                "process_failed",
                f"GraphMine exited with code {exit_code}",
                exit_code=exit_code,
            )
        return payload, command

    @staticmethod
    def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    @classmethod
    async def _terminate_and_wait(cls, process: asyncio.subprocess.Process) -> None:
        cls._terminate(process)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            await process.wait()
