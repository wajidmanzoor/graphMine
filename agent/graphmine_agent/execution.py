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
from .profiles import EXPANSION_PROBLEMS, ProfileInputError, prepare_problem_graph


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
        self._capabilities: CapabilityReport | None = None

    def probe(self) -> CapabilityReport:
        binary = self.settings.graphmine_binary
        if not binary.is_file() or not os.access(binary, os.X_OK):
            report = CapabilityReport(
                binary_available=False,
                binary_path=str(binary),
                library_version=None,
                graph_gpu_uuid=self.settings.graph_gpu_uuid,
                problem_count=len(self.catalog.instructions),
                validated_backend_count=sum(
                    len(op["backends"])
                    for op in self.catalog.manifest_problems.values()
                ),
                compiled_backend_count=0,
                problems=[],
                error="GraphMine binary is missing or not executable",
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
                problem_count=int(value["problem_count"]),
                validated_backend_count=int(value["validated_backend_count"]),
                compiled_backend_count=int(value["compiled_backend_count"]),
                problems=list(value["problems"]),
                error=(
                    None
                    if library_version == __version__
                    else (
                        "GraphMine binary version "
                        f"{library_version or 'unknown'} does not match agent "
                        f"version {__version__}"
                    )
                ),
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
                problem_count=len(self.catalog.instructions),
                validated_backend_count=sum(
                    len(op["backends"])
                    for op in self.catalog.manifest_problems.values()
                ),
                compiled_backend_count=0,
                problems=[],
                error=str(error),
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
        for problem in self.capabilities.problems:
            for backend in problem.get("backends", []):
                if backend.get("compiled"):
                    result.add(str(backend["id"]))
        return result

    def compiled_backends_for(self, problem_id: str) -> set[str]:
        for problem in self.capabilities.problems:
            if problem.get("id") == problem_id:
                return {
                    str(backend["id"])
                    for backend in problem.get("backends", [])
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
            self.compiled_backends_for(plan.problem_id)
            if self.capabilities.binary_available
            else None
        )
        graph_record = self.graph_store.database.get_file(plan.graph_id)
        if graph_record.role != FileRole.graph:
            raise UploadError("graph_id must identify a main graph file")
        plan = self.validator.validate(
            plan, compiled_backends=compiled, for_execution=True
        )
        problem = self.catalog.problem(plan.problem_id)
        graph_path = self.graph_store.execution_path(plan.graph_id, plan.session_id)
        if plan.problem_id in EXPANSION_PROBLEMS or (
            plan.application_intent and plan.application_intent.filters
        ):
            from .graph_context import project_graph

            projected = project_graph(
                self.graph_store.read_graph(plan.graph_id, plan.session_id),
                plan.application_intent.filters if plan.application_intent else [],
            )
            try:
                projected = prepare_problem_graph(projected, plan)
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
                        "problem_profile": problem.instruction.get(
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
            plan.problem_id,
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

        for name, specification in problem.instruction["parameters"].items():
            if name not in plan.parameters:
                continue
            value = plan.parameters[name]
            flag = specification["flag"]
            if specification["type"] == "boolean":
                if value:
                    command.append(flag)
            elif specification["type"] in {"vertex_id", "vertex_groups"}:
                command.extend([flag, json.dumps(value, ensure_ascii=False)])
            else:
                command.extend([flag, str(value)])

        if plan.problem_id in EXPANSION_PROBLEMS:
            command.extend(
                ["--timeout-seconds", str(self.settings.job_timeout_seconds or 0)]
            )

        for name, specification in problem.instruction["auxiliary_inputs"].items():
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
            flag = problem.instruction["optional_outputs"][output]
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
            stderr = self.stderr_tail(stderr_path)
            raise ExecutionError(
                "missing_result",
                stderr.strip() or "GraphMine did not create result.json",
                exit_code=exit_code,
            )
        payload = self.read_result(result_path)
        if exit_code not in {0, 3}:
            raise ExecutionError(
                "process_failed",
                f"GraphMine exited with code {exit_code}",
                exit_code=exit_code,
            )
        return payload, command

    def read_result(self, path: Path) -> dict[str, Any]:
        """Reject oversized files before allocating or parsing their contents.

        The source artifact remains intact. A bounded read also detects a file
        that grows or shrinks after the completed process's size check.
        """
        limit = self.settings.max_result_bytes
        try:
            with path.open("rb") as handle:
                size = os.fstat(handle.fileno()).st_size
                if limit is not None and size > limit:
                    raise ExecutionError(
                        "result_too_large",
                        f"The result exceeds the {limit}-byte loading limit. Narrow the selection or request fewer detailed instances.",
                    )
                text = handle.read(size + 1).decode("utf-8")
                if handle.tell() != size:
                    raise ExecutionError(
                        "invalid_result", "Result file changed while being read"
                    )
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as error:
            raise ExecutionError(
                "invalid_result", f"invalid result JSON: {error}"
            ) from error
        if not isinstance(payload, dict):
            raise ExecutionError(
                "invalid_result", "GraphMine result root is not an object"
            )
        return payload

    @staticmethod
    def stderr_tail(path: Path) -> str:
        # Four UTF-8 bytes per retained character; never read the full log just
        # to report its last 8,000 characters.
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 32_000))
            return handle.read(32_000).decode("utf-8", errors="replace")[-8_000:]

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
