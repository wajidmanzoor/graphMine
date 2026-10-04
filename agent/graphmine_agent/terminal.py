"""Conversational CLI using the same HTTP contract as the browser."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import shlex
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx

from .api import create_app
from .config import Settings
from .models import FileRole
from .results import summarize_result

HELP = """Ask a question in your own domain's language.
/load PATH [--directed] [--role ROLE]  Upload a graph or supporting file
/files                              List this session's uploaded files
/use FILE_ID                        Choose the graph for the next question
/direction two-way|preserve          Allow or disallow treating directed links as two-way
/run QUESTION                       Request a new computation
/plan QUESTION                      Preview a plan without running it
/explain QUESTION                   Ask about the current result
/result                             Show the full structured result
/view [FILE.html]                   Export the answer as an offline interactive report
/wait [JOB_ID]                      Wait for a pending job
/cancel [JOB_ID]                    Cancel a queued or running job
/feedback                           Describe the problem and expected behavior
/feedback WRONG | EXPECTED          Save feedback in one line
/history [FILE.zip]                 Show saved history; optionally export it
/sessions                           List saved sessions
/resume SESSION_ID                  Resume a saved session
/new [DOMAIN_ID]                    Start another session
/domains                            List domains
/help                               Show this help
/quit                               Exit
Upload roles: graph, query_graph, motif, updates, left_partition, attachment.
Use quotes around paths containing spaces. Feedback is stored for later review;
it does not train the model or change the current computation."""


class ClientError(RuntimeError):
    def __init__(self, message: str, *, turn_id: str | None = None):
        super().__init__(message)
        self.turn_id = turn_id


@asynccontextmanager
async def agent_client(
    settings: Settings,
    *,
    base_url: str | None = None,
    data_dir: Path | None = None,
) -> AsyncIterator[tuple[httpx.AsyncClient, Path | None]]:
    headers = (
        {"Authorization": f"Bearer {settings.api_token}"} if settings.api_token else {}
    )
    timeout = httpx.Timeout(600.0, connect=10.0)
    if base_url:
        async with httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout
        ) as client:
            yield client, None
        return
    # A separate store prevents a second worker from marking the live server's
    # jobs interrupted. A lock prevents two embedded CLIs sharing this store.
    root = (
        (data_dir or settings.repository_root / ".graphmine-cli").expanduser().resolve()
    )
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".cli.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ClientError(
                "Another local CLI uses this data directory. Use --base-url for a running server or choose a different --data-dir."
            ) from error
        configured = replace(settings, data_root=root)
        app = create_app(configured)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://graphmine.local",
                headers=headers,
                timeout=timeout,
            ) as client,
        ):
            yield client, configured.history_root


class Terminal:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        history_root: Path | None = None,
        timeout_seconds: float = 600,
        json_output: bool = False,
        output: Callable[[str], None] = print,
        read: Callable[[str], str] = input,
    ):
        self.client = client
        self.history_root = history_root
        self.timeout_seconds = timeout_seconds
        self.json_output = json_output
        self.output = output
        self.read = read
        self.session: dict[str, Any] | None = None
        self.graph_id: str | None = None
        self.result_id: str | None = None
        self.job_id: str | None = None
        self.turn_id: str | None = None
        self.last_outcome: dict[str, Any] = {}
        self.allow_directed_projection = False

    def emit(self, kind: str, text: str, data: Any = None) -> None:
        if self.json_output:
            self.output(
                json.dumps(
                    {"type": kind, "message": text, "data": data}, ensure_ascii=False
                )
            )
        else:
            self.output(text)

    async def prompt(self, text: str) -> str:
        """Keep local jobs progressing without leaving a blocked input thread."""
        if self.read is not input:
            return self.read(text)
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def ready() -> None:
            if future.done():
                return
            line = sys.stdin.readline()
            if line:
                future.set_result(line.rstrip("\r\n"))
            else:
                future.set_exception(EOFError())

        try:
            descriptor = sys.stdin.fileno()
            loop.add_reader(descriptor, ready)
        except (AttributeError, OSError, ValueError, NotImplementedError):
            # Regular input files cannot be registered with epoll and never wait
            # on a human, so a synchronous read is safe here.
            return self.read(text)
        try:
            print(
                text,
                end="",
                flush=True,
                file=sys.stderr if self.json_output else sys.stdout,
            )
            return await future
        finally:
            loop.remove_reader(descriptor)

    @property
    def session_id(self) -> str:
        if not self.session:
            raise ClientError("Start or resume a session first.")
        return self.session["id"]

    async def request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise ClientError(
                f"Could not contact the agent ({type(error).__name__}). Check the server address and connection."
            ) from error
        if response.is_error:
            try:
                body = response.json()
            except ValueError:
                body = {}
            detail = body.get("error", body.get("detail", body))
            message = (
                detail.get("message", str(detail))
                if isinstance(detail, dict)
                else str(detail)
            )
            if response.status_code == 401:
                message = "Authentication failed. Set GRAPHMINE_API_TOKEN to the server's token."
            elif response.status_code == 404 and path.endswith("/history"):
                message = "This server does not support history yet. Restart it with the updated code, or omit --base-url to use the local CLI."
            raise ClientError(
                message or f"HTTP {response.status_code}", turn_id=body.get("turn_id")
            )
        return response.json()

    async def start(
        self,
        domain_id: str = "general",
        title: str | None = None,
        session_id: str | None = None,
    ) -> None:
        if session_id:
            session = await self.request("GET", f"/api/sessions/{session_id}")
        else:
            session = await self.request(
                "POST", "/api/sessions", json={"domain_id": domain_id, "title": title}
            )
        self.session = session
        self.graph_id = self.result_id = self.job_id = self.turn_id = None
        self.allow_directed_projection = False
        files = await self.request("GET", f"/api/sessions/{self.session_id}/files")
        graphs = [item for item in files if item["role"] == "graph"]
        if graphs:
            self.graph_id = graphs[-1]["id"]
        jobs = await self.request(
            "GET", "/api/jobs", params={"session_id": self.session_id}
        )
        if jobs:
            self.job_id = jobs[-1]["id"]
            self.turn_id = jobs[-1].get("turn_id")
            self.result_id = jobs[-1].get("result_id")
        # Include rejected/ambiguous requests, which never became a job.
        manifest = await self.request("GET", f"/api/sessions/{self.session_id}/history")
        latest_chat = manifest.get("last_chat")
        if latest_chat:
            self.turn_id = latest_chat["turn_id"]
            response = (
                latest_chat["data"] if latest_chat["type"] == "chat.response" else {}
            )
            self.job_id = response.get("job_id")
            self.result_id = response.get("result_id")
            if self.job_id:
                job = await self.request("GET", f"/api/jobs/{self.job_id}")
                self.result_id = job.get("result_id")
        if self.history_root and not latest_chat:
            turn_files = list(
                (self.history_root / self.session_id / "turns").glob("*.json")
            )
            if turn_files:
                latest = max(turn_files, key=lambda p: p.stat().st_mtime_ns)
                self.turn_id = latest.stem
        self.emit(
            "session", f"Session: {self.session_id} ({session['domain_id']})", session
        )
        if self.history_root:
            self.emit("history", f"History: {self.history_root / self.session_id}")
        if not manifest.get("files"):
            self.emit("notice", "This session has no recorded history yet.")

    async def load(
        self,
        path: Path,
        *,
        role: str = "graph",
        directed: bool = False,
        source_column: str | None = None,
        target_column: str | None = None,
        timestamp_unit: str | None = None,
    ) -> dict[str, Any]:
        path = path.expanduser()
        with path.open("rb") as stream:
            record = await self.request(
                "POST",
                f"/api/sessions/{self.session_id}/files",
                files={
                    "file": (
                        path.name,
                        stream,
                        "application/json" if path.suffix == ".json" else "text/plain",
                    )
                },
                data={
                    "role": role,
                    "directed": str(directed).lower(),
                    **{
                        key: value
                        for key, value in {
                            "source_column": source_column,
                            "target_column": target_column,
                            "timestamp_unit": timestamp_unit,
                        }.items()
                        if value
                    },
                },
            )
        if role == "graph":
            self.graph_id = record["id"]
            self.result_id = self.job_id = self.turn_id = None
            self.allow_directed_projection = False
        metadata = record.get("metadata") or {}
        summary = f"Loaded {path.name} as {role}."
        if "vertex_count" in metadata:
            summary += f" {metadata['vertex_count']} entities, {metadata['edge_count']} connections; {'directed' if metadata['directed'] else 'undirected'}."
        self.emit("upload", summary, record)
        return record

    async def ask(
        self, message: str, *, mode: str = "auto", execute: bool = True
    ) -> dict[str, Any]:
        # Never let feedback on a failed new question silently target an old job.
        previous_result = self.result_id
        self.job_id = self.turn_id = None
        self.last_outcome = {"query": message}
        self.emit("progress", "Thinking…")
        try:
            response = await self.request(
                "POST",
                f"/api/sessions/{self.session_id}/chat",
                json={
                    "message": message,
                    "graph_id": self.graph_id,
                    "result_id": previous_result,
                    "mode": mode,
                    "execute": execute,
                    "allow_directed_projection": self.allow_directed_projection,
                },
            )
        except ClientError as error:
            self.turn_id = error.turn_id
            self.result_id = None
            self.last_outcome["error"] = str(error)
            raise
        self.turn_id = response.get("turn_id")
        self.job_id = response.get("job_id")
        self.result_id = response.get("result_id")
        self.last_outcome["response"] = response
        if not response.get("interpretation") or self.json_output:
            self.emit("response", response["message"], response)
        if response.get("plan") and not execute:
            self.emit("plan", json.dumps(response["plan"], indent=2), response["plan"])
        if self.job_id:
            await self.wait(self.job_id)
        elif response.get("interpretation"):
            self.show_interpretation(response["interpretation"])
            if response.get("interpretation_source") == "fallback":
                result = await self.request("GET", f"/api/results/{self.result_id}")
                self.show_computed_preview(result)
        return self.last_outcome

    async def wait(self, job_id: str | None = None) -> dict[str, Any]:
        identifier = job_id or self.job_id
        if not identifier:
            raise ClientError("There is no job to wait for.")
        deadline = time.monotonic() + self.timeout_seconds
        previous_status = None
        while True:
            job = await self.request("GET", f"/api/jobs/{identifier}")
            if job["session_id"] != self.session_id:
                raise ClientError(
                    "That job belongs to a different session. Use /resume first."
                )
            self.job_id = identifier
            self.turn_id = job.get("turn_id") or self.turn_id
            self.last_outcome["job"] = job
            if job["status"] != previous_status:
                self.emit("job", f"Analysis {job['status']} ({identifier}).", job)
                previous_status = job["status"]
            if job["status"] == "completed":
                self.result_id = job["result_id"]
                result = await self.request("GET", f"/api/results/{self.result_id}")
                self.last_outcome["result"] = result
                self.show_interpretation(result.get("interpretation") or {})
                if self.history_root:
                    self.emit(
                        "view",
                        f"Interactive answer: {self.history_root / self.session_id / 'results' / self.result_id / 'answer.html'}",
                    )
                if result.get("interpretation_source") == "fallback":
                    self.show_computed_preview(result)
                return job
            if job["status"] in {"failed", "cancelled"}:
                self.result_id = job.get("result_id")
                raise ClientError(
                    (job.get("error") or {}).get("message", "Analysis was cancelled."),
                    turn_id=self.turn_id,
                )
            if time.monotonic() >= deadline:
                raise ClientError(
                    f"Stopped waiting for {identifier}. Use /wait {identifier} to check it or /cancel to cancel it.",
                    turn_id=self.turn_id,
                )
            await asyncio.sleep(0.2)

    def show_interpretation(self, interpretation: dict[str, Any]) -> None:
        if self.json_output:
            self.emit(
                "interpretation", interpretation.get("summary", ""), interpretation
            )
            return
        lines = [interpretation.get("summary", "No interpretation is available.")]
        lines.extend(f"  • {item}" for item in interpretation.get("findings", []))
        lines.extend(
            f"Possible implication (model suggestion, not a verified finding): {item}"
            for item in interpretation.get("hypotheses", [])
        )
        lines.extend(
            f"Limitation: {item}" for item in interpretation.get("limitations", [])
        )
        for view in interpretation.get("visualizations", []):
            lines.append(
                f"Suggested view: {view['title']} ({view['type']}); saved in history."
            )
        followups = interpretation.get("suggested_followups", [])
        if followups:
            lines.append("You could ask: " + followups[0])
        self.output("\n".join(lines))

    def show_computed_preview(self, result: dict[str, Any]) -> None:
        output = result["payload"]["output"]
        preview = summarize_result(output, item_limit=10)
        ranking = output.get("ranking")
        if isinstance(ranking, list):
            lines = ["Computed ranking:"]
            lines.extend(
                f"  {index}. {item['vertex']}: {item['score']}"
                for index, item in enumerate(ranking[:10], 1)
            )
            if len(ranking) > 10:
                lines.append(
                    f"Showing 10 of {len(ranking)} entries; /result shows all."
                )
            text = "\n".join(lines)
        else:
            text = "Computed output preview (/result shows all):\n" + json.dumps(
                preview, indent=2, ensure_ascii=False
            )
        self.emit("computed_result", text, preview)

    async def feedback(
        self, wrong: str, expected: str, *, source: str = "user"
    ) -> dict[str, Any]:
        record = await self.request(
            "POST",
            f"/api/sessions/{self.session_id}/feedback",
            json={
                "what_went_wrong": wrong,
                "expected_behavior": expected,
                "source": source,
                "turn_id": self.turn_id,
                "job_id": self.job_id,
                "result_id": self.result_id,
            },
        )
        self.emit("feedback", f"Feedback saved: {record['id']}", record)
        return record

    async def export(self, destination: Path) -> None:
        destination = destination.expanduser().resolve()
        if destination.exists():
            raise ClientError(
                f"Export already exists: {destination}. Choose a new filename."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with self.client.stream(
                "GET", f"/api/sessions/{self.session_id}/history/archive"
            ) as response:
                response.raise_for_status()
                with tempfile.NamedTemporaryFile(
                    prefix=f".{destination.name}.", dir=destination.parent
                ) as stream:
                    async for chunk in response.aiter_bytes():
                        stream.write(chunk)
                    stream.flush()
                    # Atomic publication without replacing a pre-existing file,
                    # including one created while the download was in progress.
                    os.link(stream.name, destination)
        except FileExistsError as error:
            raise ClientError(
                f"Export already exists: {destination}. Choose a new filename."
            ) from error
        except httpx.HTTPError as error:
            raise ClientError(
                f"History export failed ({type(error).__name__}). Check the server connection and token."
            ) from error
        self.emit("history", f"History exported to {destination}")

    async def dispatch(self, line: str) -> bool:
        line = line.strip()
        if not line:
            return True
        if not line.startswith("/"):
            await self.ask(line)
            return True
        command, _, argument = line.partition(" ")
        argument = argument.strip()
        if command in {"/quit", "/exit"}:
            return False
        if command == "/help":
            self.emit("help", HELP)
        elif command in {"/run", "/plan", "/explain"}:
            if not argument:
                raise ClientError(f"Add your question after {command}.")
            await self.ask(
                argument,
                mode="analyst" if command == "/explain" else "planner",
                execute=command != "/plan",
            )
        elif command == "/load":
            parts = shlex.split(argument)
            if not parts:
                raise ClientError("Use /load PATH [--directed] [--role ROLE].")
            path = parts.pop(0)
            role, directed = "graph", False
            columns = {}
            while parts:
                flag = parts.pop(0)
                if flag == "--directed":
                    directed = True
                elif flag == "--role" and parts:
                    role = FileRole(parts.pop(0)).value
                elif (
                    flag in {"--source-column", "--target-column", "--timestamp-unit"}
                    and parts
                ):
                    columns[flag[2:].replace("-", "_")] = parts.pop(0)
                else:
                    raise ClientError(f"Unknown or incomplete upload option: {flag}")
            await self.load(Path(path), role=role, directed=directed, **columns)
        elif command == "/feedback":
            if argument:
                wrong, separator, expected = argument.partition("|")
                if not separator:
                    raise ClientError(
                        "Use /feedback what went wrong | what you expected."
                    )
            else:
                wrong = await self.prompt("What went wrong? ")
                expected = await self.prompt("What did you expect? ")
            await self.feedback(wrong, expected)
        elif command == "/view":
            if not self.result_id:
                raise ClientError("There is no result to export yet.")
            parts = (
                shlex.split(argument)
                if argument
                else [f"graphmine-{self.result_id}.html"]
            )
            if len(parts) != 1:
                raise ClientError("Use /view FILE.html (quote paths with spaces).")
            destination = Path(parts[0]).expanduser().resolve()
            if destination.exists():
                raise ClientError(
                    "That file already exists; choose a new report filename."
                )
            response = await self.client.get(f"/api/results/{self.result_id}/report")
            response.raise_for_status()
            with destination.open("xb") as stream:
                destination.chmod(0o600)
                stream.write(response.content)
            self.emit(
                "view",
                f"Open this offline interactive report in your browser: {destination}",
            )
        elif command == "/history":
            if argument:
                parts = shlex.split(argument)
                if len(parts) != 1:
                    raise ClientError(
                        "Use /history FILE.zip (quote paths with spaces)."
                    )
                await self.export(Path(parts[0]))
            else:
                manifest = await self.request(
                    "GET", f"/api/sessions/{self.session_id}/history"
                )
                location = (
                    str(self.history_root / self.session_id)
                    if self.history_root
                    else "the agent server (use /history FILE.zip to download)"
                )
                self.emit(
                    "history",
                    f"{len(manifest['files'])} history files in {location}",
                    manifest,
                )
        elif command in {"/sessions", "/domains", "/files"}:
            path = (
                f"/api/sessions/{self.session_id}/files"
                if command == "/files"
                else f"/api{command}"
            )
            records = await self.request("GET", path)
            self.emit(
                command[1:],
                "\n".join(
                    f"{item['id']}  {item.get('name') or item.get('original_name') or item.get('title') or item.get('domain_id', '')}"
                    for item in records
                )
                or "None yet.",
                records,
            )
        elif command == "/new":
            await self.start(domain_id=argument or "general")
        elif command == "/resume":
            if not argument:
                raise ClientError("Use /resume SESSION_ID.")
            await self.start(session_id=argument)
        elif command == "/use":
            files = await self.request("GET", f"/api/sessions/{self.session_id}/files")
            if not any(
                item["id"] == argument and item["role"] == "graph" for item in files
            ):
                raise ClientError("Choose a graph file ID from /files.")
            self.graph_id = argument
            self.result_id = self.job_id = self.turn_id = None
            self.allow_directed_projection = False
            self.emit("graph", f"Selected graph: {argument}")
        elif command == "/direction":
            if argument not in {"two-way", "preserve"}:
                raise ClientError(
                    "Use /direction two-way to allow treating directed links as two-way, or /direction preserve to retain their meaning."
                )
            self.allow_directed_projection = argument == "two-way"
            self.emit(
                "direction",
                "Directed links may be treated as two-way for this graph."
                if self.allow_directed_projection
                else "Directed links must retain their direction.",
            )
        elif command == "/wait":
            await self.wait(argument or None)
        elif command == "/cancel":
            identifier = argument or self.job_id
            if not identifier:
                raise ClientError("There is no job to cancel.")
            job = await self.request("GET", f"/api/jobs/{identifier}")
            if job["session_id"] != self.session_id:
                raise ClientError("That job belongs to a different session.")
            job = await self.request("DELETE", f"/api/jobs/{identifier}")
            self.emit("job", f"Analysis {job['status']}.", job)
        elif command == "/result":
            if not self.result_id:
                raise ClientError(
                    "There is no current result. Ask a question or use /wait first."
                )
            record = await self.request("GET", f"/api/results/{self.result_id}")
            self.emit(
                "result", json.dumps(record, indent=2, ensure_ascii=False), record
            )
        else:
            raise ClientError(f"Unknown command: {command}. Use /help.")
        return True


async def run_chat(settings: Settings, arguments: Any) -> int:
    async with agent_client(
        settings, base_url=arguments.base_url, data_dir=arguments.data_dir
    ) as (client, history_root):
        terminal = Terminal(
            client,
            history_root=history_root,
            timeout_seconds=arguments.timeout_seconds,
            json_output=arguments.json,
        )
        health = await terminal.request("GET", "/api/health")
        if not health["llm"]["enabled"]:
            terminal.emit(
                "notice",
                "Offline rules are enabled. Domain-language understanding requires the configured language model.",
            )
        elif not health["llm"]["available"]:
            terminal.emit(
                "notice",
                "The language model is unavailable. Uploads, history, and feedback still work.",
            )
        await terminal.start(
            domain_id=arguments.domain,
            title=arguments.title,
            session_id=arguments.session,
        )
        if arguments.graph:
            await terminal.load(arguments.graph, directed=arguments.directed)
        errors = False
        lines = list(arguments.message or [])
        if arguments.script:
            lines.extend(arguments.script.read_text(encoding="utf-8").splitlines())
        batch = bool(arguments.message) or arguments.script is not None
        if not batch:
            terminal.emit(
                "welcome",
                "Describe your graph and question in your own words. Use /load PATH to upload data; /help lists commands.",
            )
        while True:
            try:
                if batch:
                    if not lines:
                        break
                    line = lines.pop(0)
                else:
                    line = await terminal.prompt("graphmine> ")
                if not await terminal.dispatch(line):
                    break
            except EOFError:
                break
            except (ClientError, OSError, ValueError) as error:
                errors = True
                terminal.emit("error", str(error))
        return 1 if errors and batch else 0


def chat_main(settings: Settings, arguments: Any) -> int:
    try:
        return asyncio.run(run_chat(settings, arguments))
    except KeyboardInterrupt:
        print(
            "\nCLI stopped. Local active jobs are cancelled; remote jobs can be resumed with /wait.",
            file=sys.stderr,
        )
        return 130
    except (ClientError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
