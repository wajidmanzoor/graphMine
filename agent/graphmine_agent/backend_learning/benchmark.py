"""Offline, resumable native benchmarks. Never invoked by the web application."""

from __future__ import annotations

import argparse
import asyncio
import csv
import fcntl
import hashlib
import json
import os
import signal
import statistics
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .benchmark_graphs import NAME, dataset_settings, digest, prepare_graph
from .benchmark_profiles import attempt_keys, bind_parameters, expand_graphs, load_config, parameter_grid, select_graphs
from .features import graph_features, safe_parameters
from .hardware import PeakSampler, hardware_snapshot, merge_peaks
from .leases import GPULock
from .memory import effective_rows
from .storage import SCHEMA_VERSION, RunLog, atomic_json, prepare_directories, read_rows, utc_now
from ..calculation_limits import minimum_limit, remaining_seconds

ROOT = Path(__file__).resolve().parents[3]


class LeaseBusy(ValueError):
    pass


def code_hash():
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(Path(__file__).parent.glob("*.py"))})


def _native_environment(root, library, *, gpu_uuid=None):
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env.update(PYTHONPATH=os.pathsep.join((str(root / "agent"), str(root / "python/graphmine"))),
               GRAPHMINE_REPOSITORY_ROOT=str(root), GRAPHMINE_NATIVE_LIBRARY=str(library),
               CUDA_VISIBLE_DEVICES=gpu_uuid or "", PYTHONUNBUFFERED="1")
    return env


def process_identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return dict(pid=pid, start_ticks=fields[19], boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip())
    except (OSError, ValueError, IndexError):
        return None


def same_process(identity):
    return bool(identity and process_identity(identity["pid"]) == identity)


@contextmanager
def exclusive(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LeaseBusy("Another benchmark process holds this collection lease") from error
        yield fd
    finally:
        os.close(fd)


def _decorate(row, job):
    row.update(run_id=job["run_id"], benchmark_id=job["benchmark_id"], benchmark_mode=job["benchmark_mode"],
               graph_id=job["graph_id"], comparison_id=job["comparison_id"],
               benchmark_pair_id=job["benchmark_pair_id"], benchmark_attempt_key=job["benchmark_attempt_key"],
               repetition=job["repetition"], source="benchmark", is_evaluation=job["is_evaluation"],
               implementation_sha256=job["implementation_sha256"])
    return row


def initial_row(job, graph, card, gpu_uuid):
    from graphmine.registry import algorithm

    hardware = hardware_snapshot(leased_gpu_uuid=gpu_uuid)
    backend = job["backend"]
    candidates = [dict(id=c["id"], device=c["device"], compiled=c["compiled"], admitted=c.get("verified", False),
                       feasible=False, infeasible_reason="preflight_not_completed") for c in card["backends"]]
    row = dict(schema_version=SCHEMA_VERSION, run_id=job["run_id"], workflow_id=job["benchmark_id"],
               step_id=job["benchmark_attempt_key"], created_at=utc_now(), operation=job["operation"],
               problem_id=card["problem_id"], family=card["family"],
               parameters=safe_parameters(job["parameters"], algorithm(job["operation"]).parameters),
               requested_device="cpu" if backend == "cpp" else "gpu", requested_backend=backend,
               candidates=candidates, chosen_backend=backend, reason="forced", policy_version="feasibility-v1",
               model_version=None, predictions={}, hardware=hardware,
               graph_features=graph_features(graph, input_kind="graph"), outcome=None, error_code=None,
               runtime_seconds=None, native_elapsed_seconds=None, native_compute_seconds=None,
               preparation_seconds=None, timeout_seconds=job["budget"]["timeout_seconds"], censored=False,
               peak_memory=dict(gpu_bytes=None, process_rss_bytes=None, sample_interval_seconds=0.1),
               output_size=None, output_estimate=job["budget"]["max_output_items"], fallback_chain=[],
               execution_started=False, failure_stage="preflight", prediction_error=None,
               implementation_sha256=job["implementation_sha256"], telemetry_warnings=hardware.get("warnings", []))
    return _decorate(row, job)


def child(request_path):
    """One verified backend in one process; stdout contains aggregate events only."""
    request_path = Path(request_path)
    atomic_json(request_path.with_name("worker.json"), process_identity(os.getpid()))
    from graphmine import evidence
    from graphmine.contracts import Budget
    from graphmine.dispatch import implementation_hash, run
    from graphmine.native_inputs import Graph
    from ..evidence_cache import install
    from .worker import run_observed

    job = json.loads(request_path.read_text())
    attempt_dir = request_path.parent
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    os.environ["GRAPHMINE_BACKEND_DATA_DIR"] = job["data_dir"]

    def emit(event):
        if "record" in event:
            row = _decorate(event["record"], job)
            path = attempt_dir / ("terminal.json" if event["event"] == "native_finished" else "started.json")
            try:
                atomic_json(path, row)
            except OSError:
                row["telemetry_warnings"].append("benchmark_journal_write_failed")
        protocol.write(json.dumps(event, separators=(",", ":"), allow_nan=False) + "\n")

    try:
        install(evidence, Path(job["data_dir"]) / "benchmarks" / job["benchmark_id"] / "evidence-hashes.json")
        if implementation_hash() != job["implementation_sha256"]:
            raise ValueError("Native implementation changed during benchmark")
        caps = evidence.capabilities(Path(job["repository_root"]))
        card = next(c for c in caps["operations"] if c["id"] == job["operation"])
        allowed = [b["id"] for b in card["backends"] if b.get("verified") and b["compiled"]
                   and (b["device"] == "cpu" or job["gpu_uuid"] in b.get("verified_devices", []))]
        if job["backend"] not in allowed:
            raise ValueError("Requested backend has no current evidence on this device")
        data = json.loads(Path(job["graph_path"]).read_text())
        if digest(data) != job["graph_fingerprint"]:
            raise ValueError("Benchmark graph changed")
        graph = Graph(data)
        remaining = remaining_seconds(job["deadline_monotonic"])
        if remaining is not None and remaining <= 0:
            raise TimeoutError("Benchmark startup exceeded its deadline")
        budget = Budget(**{**job["budget"], "timeout_seconds": minimum_limit(remaining, job["budget"]["timeout_seconds"])})
        run_observed(run, job["operation"], graph, context=dict(source="benchmark", workflow_id=job["benchmark_id"],
                     is_evaluation=job["is_evaluation"], leased_gpu_uuid=job["gpu_uuid"],
                     backend_memory_safety=job["memory_safety"], job_timeout_seconds=remaining),
                     step_id=job["benchmark_attempt_key"], emit=emit, parameters=job["parameters"],
                     device="cpu" if job["backend"] == "cpp" else "gpu", backend=job["backend"],
                     gpu_device=0, allowed_backends=allowed, budget=budget)
        return 0
    except BaseException as error:
        # Never echo graph identifiers, parameter values, or credentials.
        print("benchmark worker failed: " + type(error).__name__, file=sys.stderr)
        return 2
    finally:
        protocol.close()


async def run_attempt(job, row, directory, *, python, library, lock=None, command=None):
    """Hard deadline and process-tree sampling survive a killed native worker."""
    path = Path(directory) / "attempts" / job["benchmark_attempt_key"]
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    started = time.monotonic()
    timeout = job["budget"]["timeout_seconds"]
    job = {**job, "deadline_monotonic": started + timeout if timeout is not None else None}
    atomic_json(path / "request.json", job)
    state = dict(record=row, process=None, status="starting")
    atomic_json(path / "state.json", state)
    process = None
    sampler = None
    terminal, timed_out, cancelled = None, False, False
    warnings = []
    diagnostics = 0

    async def stdout():
        nonlocal row, terminal
        while raw := await process.stdout.readline():
            event = json.loads(raw)
            if event.get("event") not in {"native_started", "native_finished", "telemetry_warning"}:
                raise ValueError("Unexpected benchmark worker event")
            if "record" not in event:
                warnings.append(event.get("code", "worker_telemetry_warning"))
                continue
            observed = event["record"]
            if (observed.get("run_id") != job["run_id"]
                    or observed.get("benchmark_attempt_key") != job["benchmark_attempt_key"]):
                raise ValueError("Benchmark worker returned another attempt")
            row = observed
            if event["event"] == "native_finished":
                if terminal is not None:
                    raise ValueError("Duplicate terminal event")
                terminal = observed
            else:
                state["record"] = observed
                try:
                    atomic_json(path / "state.json", state)
                except OSError:
                    warnings.append("benchmark_journal_write_failed")

    async def stderr():
        nonlocal diagnostics
        while raw := await process.stderr.read(65536):
            diagnostics += len(raw)  # Native diagnostics are discarded, never training data.

    readers = []
    attempt_lease = exclusive(path / "worker.lock")
    attempt_fd = attempt_lease.__enter__()
    try:
        process = await asyncio.create_subprocess_exec(
            *(command or [str(python), "-m", "graphmine_agent.backend_learning.benchmark", "--child", str(path / "request.json")]),
            env=_native_environment(Path(job["repository_root"]), library, gpu_uuid=job["gpu_uuid"]),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True, pass_fds=(attempt_fd, *((lock.fd,) if lock else ())), limit=512 * 1024)
        state.update(process=process_identity(process.pid), status="running")
        try:
            atomic_json(path / "state.json", state)
        except OSError:
            warnings.append("benchmark_journal_write_failed")
        try:
            sampler = PeakSampler(process.pid, 1 if job["gpu_uuid"] else None)
        except Exception:
            warnings.append("peak_sampler_failed")
        readers = [asyncio.create_task(stdout()), asyncio.create_task(stderr())]
        remaining = remaining_seconds(job["deadline_monotonic"])
        await asyncio.wait_for(asyncio.gather(*readers, process.wait()),
                               max(0.001, remaining) if remaining is not None else None)
    except TimeoutError:
        timed_out = True
    except asyncio.CancelledError:
        cancelled = True
    except Exception:
        warnings.append("benchmark_worker_protocol_failed")
    finally:
        # The process group can still contain an isolated CUDA worker even if
        # the Python leader exited. Always clean the group before releasing GPU 1.
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
        for task in readers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        if sampler is not None:
            try:
                row["peak_memory"] = merge_peaks(row["peak_memory"], sampler.finish())
                warnings.extend(sampler.warnings)
            except Exception:
                warnings.append("peak_sampler_failed")
        wall = time.monotonic() - started
        if timed_out:
            row.update(outcome="timeout", error_code="timeout", censored=True,
                       runtime_seconds=max(row["timeout_seconds"] or 0, row.get("runtime_seconds") or 0))
        elif cancelled:
            row.update(outcome="error", error_code="cancelled", censored=False, runtime_seconds=wall)
        elif terminal is None:
            row.update(outcome="error", error_code="worker_no_terminal_row", runtime_seconds=wall, censored=False)
        row.update(attempt_wall_seconds=wall, worker_diagnostic_bytes=diagnostics)
        row["telemetry_warnings"].extend(warnings)
        if cancelled:
            # Caller still publishes the terminal row before propagating cancel.
            row["benchmark_cancelled"] = True
        try:
            atomic_json(path / "terminal.json", row)
        except OSError:
            row["telemetry_warnings"].append("benchmark_journal_write_failed")
        finally:
            attempt_lease.__exit__(None, None, None)
    return row


def recorded_rows(directory):
    path = Path(directory) / "runs.jsonl"
    if not path.exists():
        return []
    result = []
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
            if not row.get("benchmark_attempt_key") or not row.get("run_id") or not row.get("outcome"):
                raise ValueError("Incomplete benchmark row")
            result.append(row)
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Benchmark run log is damaged; preserve it and repair with append-only corrections") from None
    return effective_rows(result)


async def publish(logger, row, directory):
    if not logger.submit(row):
        raise OSError("Run completed but its log could not be queued; terminal journal was retained")
    await asyncio.wait_for(asyncio.to_thread(logger.flush), 10)
    if row["run_id"] not in {r["run_id"] for r in recorded_rows(directory)}:
        raise OSError("Run completed but logging failed; resume from the retained terminal journal")
    state = Path(directory) / "attempts" / row["benchmark_attempt_key"] / "state.json"
    atomic_json(state, dict(status="recorded", record=row, process=None))


async def recover(directory, logger):
    """Do not restart an uncertain attempt or a verified live worker."""
    rows = recorded_rows(directory)
    seen = {r["benchmark_attempt_key"] for r in rows}
    for state_path in sorted((Path(directory) / "attempts").glob("*/state.json")):
        state = json.loads(state_path.read_text())
        row = state["record"]
        key = row["benchmark_attempt_key"]
        if key in seen:
            continue
        while True:
            identity = state.get("process")
            identity_path = state_path.with_name("worker.json")
            if identity is None and identity_path.exists():
                identity = json.loads(identity_path.read_text())
            try:
                with exclusive(state_path.with_name("worker.lock")):
                    locked = False
            except LeaseBusy:
                locked = True
            alive = same_process(identity)
            if not alive and not locked:
                break
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"])).total_seconds()
            if row["timeout_seconds"] is not None and elapsed >= row["timeout_seconds"]:
                if alive:
                    try:
                        os.killpg(identity["pid"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                elif locked:
                    raise ValueError("A surviving benchmark worker still holds its attempt lease; preserve and resume this collection")
            await asyncio.sleep(0.2)
        terminal = state_path.with_name("terminal.json")
        if terminal.exists():
            result = json.loads(terminal.read_text())
            if result["run_id"] != row["run_id"] or result["benchmark_attempt_key"] != key:
                raise ValueError("Interrupted benchmark journal has inconsistent identity")
            row = result
        else:
            if state_path.with_name("started.json").exists():
                row = json.loads(state_path.with_name("started.json").read_text())
            elapsed = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"])).total_seconds())
            timed_out = row["timeout_seconds"] is not None and elapsed >= row["timeout_seconds"]
            row.update(outcome="timeout" if timed_out else "error", censored=timed_out,
                       error_code="interrupted_timeout" if timed_out else "interrupted",
                       runtime_seconds=minimum_limit(elapsed, row["timeout_seconds"]))
            row["telemetry_warnings"].append("recovered_without_live_samples")
        await publish(logger, row, directory)
        seen.add(key)
    return recorded_rows(directory)


def bootstrap_totals(data_dir, implementation, is_evaluation):
    """Count durable rows and unfinished claims across collection IDs."""
    prior = effective_rows(read_rows(data_dir))
    identities = {r["run_id"] for r in prior}
    for path in Path(data_dir).glob("benchmarks/*/attempts/*/state.json"):
        row = json.loads(path.read_text())["record"]
        if row["run_id"] not in identities:
            prior.append(row)
            identities.add(row["run_id"])
    return Counter(r["operation"] for r in prior if r.get("source") == "benchmark"
        and r.get("implementation_sha256") == implementation and r.get("is_evaluation") is is_evaluation)


def summarize(rows, cards):
    measurements = defaultdict(lambda: defaultdict(list))
    by_operation = defaultdict(Counter)
    for row in rows:
        by_operation[row["operation"]][row["outcome"]] += 1
        measurements[row["comparison_id"]][row["requested_backend"]].append(row)
    comparisons, wins = [], Counter()
    by_id = {c["id"]: c for c in cards}
    for comparison, groups in sorted(measurements.items()):
        first = next(iter(groups.values()))[0]
        medians, backends = {}, []
        for backend, attempts in sorted(groups.items()):
            times = [r["runtime_seconds"] for r in attempts if r["outcome"] == "completed" and not r.get("censored")]
            median = statistics.median(times) if times else None
            if median is not None:
                medians[backend] = median
            backends.append(dict(backend=backend, attempts=len(attempts), completed=len(times), median_seconds=median,
                                 minimum_seconds=min(times) if times else None, maximum_seconds=max(times) if times else None,
                                 spread_seconds=max(times) - min(times) if times else None))
        best = min(medians.values()) if medians else None
        fastest = sorted(b for b, value in medians.items() if value == best)
        for backend in fastest:
            wins[first["operation"], backend] += 1
        admitted = {b["id"] for b in by_id[first["operation"]]["backends"] if b.get("verified")}
        comparisons.append(dict(comparison_id=comparison, operation=first["operation"], graph_id=first["graph_id"],
                                 backends=backends, fastest_observed_backends=fastest,
                                 admitted_backend_count=len(admitted), complete_backend_coverage=admitted <= medians.keys()))
    return dict(schema_version=1, created_at=utc_now(), rows=len(rows),
                evaluation_rows=sum(r["is_evaluation"] for r in rows),
                per_operation={op: dict(counts) for op, counts in sorted(by_operation.items())},
                comparisons=comparisons,
                wins=[dict(operation=op, backend=b, wins=n) for (op, b), n in sorted(wins.items())],
                scope="Fastest observed backend for an identical graph, parameters, budget and implementation; incomplete coverage is explicit")


def summary_table(directory, summary):
    """A derived, readable table; authoritative observations remain JSONL."""
    path = Path(directory) / "summary.csv"
    temporary = path.with_name(path.name + "." + uuid4().hex)
    fields = ("operation", "graph_id", "backend", "attempts", "completed", "median_seconds",
              "minimum_seconds", "maximum_seconds", "spread_seconds", "fastest_observed",
              "complete_backend_coverage", "comparison_id")
    try:
        with temporary.open("x", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for comparison in summary["comparisons"]:
                for backend in comparison["backends"]:
                    writer.writerow({**backend, **{k: comparison[k] for k in
                        ("operation", "graph_id", "complete_backend_coverage", "comparison_id")},
                        "fastest_observed": backend["backend"] in comparison["fastest_observed_backends"]})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


async def collect(arguments):
    from ..config import Settings
    from graphmine import evidence
    from graphmine.dispatch import implementation_hash
    from ..evidence_cache import install

    settings = dataset_settings(Settings.from_env(ROOT), registry=arguments.registry,
        instances=arguments.instances, password_file=arguments.password_file)
    data_dir, model_dir = arguments.data_dir or settings.backend_data_dir, arguments.model_dir or settings.backend_model_dir
    prepare_directories(data_dir, model_dir, ROOT)
    library = (arguments.native_library or settings.native_runtime_library or ROOT / "library/build/runtime/libgraphmine_runtime.so").resolve()
    os.environ.update(GRAPHMINE_NATIVE_LIBRARY=str(library), CUDA_VISIBLE_DEVICES="")
    config = load_config(arguments.config)
    if arguments.examples_per_operation is not None:
        config["bootstrap_examples_per_operation"] = arguments.examples_per_operation
    is_evaluation = bool(arguments.is_evaluation or os.environ.get("PYTEST_CURRENT_TEST")
                         or os.environ.get("GRAPHMINE_IS_EVALUATION") == "true")
    mode = "full" if arguments.full else "bootstrap"
    identifier = arguments.benchmark_id or datetime.now(timezone.utc).strftime("bootstrap-%Y%m%dt%H%M%Sz")
    if not NAME.fullmatch(identifier):
        raise ValueError("Invalid benchmark ID")
    directory = Path(data_dir) / "benchmarks" / identifier
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    install(evidence, directory / "evidence-hashes.json")
    caps, implementation = evidence.capabilities(ROOT), implementation_hash()
    cards = [c for c in caps["operations"] if sum(b.get("verified", False) for b in c["backends"]) > 1]
    if arguments.operations:
        missing = set(arguments.operations) - {c["id"] for c in cards}
        if missing:
            raise ValueError("Requested operations have no admitted backend comparison: " + ", ".join(sorted(missing)))
        cards = [c for c in cards if c["id"] in arguments.operations]
    if not cards:
        raise ValueError("No admitted multi-backend operations")
    gpu = next((g for g in hardware_snapshot()["gpus"] if g["index"] == 1), None)
    if gpu is None:
        raise ValueError("Physical GPU 1 is unavailable")
    for card in cards:
        for backend in card["backends"]:
            if backend.get("verified") and backend["device"] == "gpu" and gpu["uuid"] not in backend.get("verified_devices", []):
                raise ValueError("An admitted backend lacks evidence on physical GPU 1")
    frozen_code = code_hash()
    manifest = dict(schema_version=1, mode=mode, is_evaluation=is_evaluation, config=config,
                    implementation_sha256=implementation, native_library_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
                    benchmark_code_sha256=frozen_code, gpu_index=1, gpu_uuid=gpu["uuid"],
                    operations=[dict(operation=c["id"], backends=[b["id"] for b in c["backends"] if b.get("verified")]) for c in cards])
    selection = select_graphs(config, cards, full=arguments.full)
    with exclusive(directory / "collection.lock"), exclusive(Path(data_dir) / "locks" / ("bootstrap.lock" if not arguments.full else identifier + ".lock")):
        config_path = directory / "config.json"
        if config_path.exists():
            if json.loads(config_path.read_text()) != manifest:
                raise ValueError("Benchmark config, code or implementation changed; use a new benchmark ID")
        else:
            atomic_json(config_path, manifest)
        logger = RunLog(data_dir, destination=directory / "runs.jsonl")
        try:
            rows = await recover(directory, logger)
            seen = {r["benchmark_attempt_key"] for r in rows}
            totals = bootstrap_totals(data_dir, implementation, is_evaluation)
            for card in sorted(cards, key=lambda c: c["id"]):
                operation = card["id"]
                admitted = [b["id"] for b in card["backends"] if b.get("verified")]
                # CPU first, then native declaration order; repeat only after
                # every backend has had an opportunity within the initial cap.
                backends = ["cpp", *(b for b in admitted if b != "cpp")]
                if "cpp" not in admitted:
                    raise ValueError("The benchmark requires admitted cpp evidence")
                if not arguments.full and "bootstrap_backends" in config["operations"][operation]:
                    backends = config["operations"][operation]["bootstrap_backends"]
                    if (not isinstance(backends, list) or not backends or backends[0] != "cpp"
                            or len(set(backends)) != len(backends) or not set(backends) <= set(admitted)):
                        raise ValueError("Bootstrap backend subsets must start with cpp and contain unique admitted backends")
                limit = None if arguments.full else config["bootstrap_examples_per_operation"]
                for spec in selection[operation]:
                    if limit is not None and totals[operation] >= limit:
                        break
                    graph_path, graph_meta = prepare_graph(directory, spec, settings)
                    graph = json.loads(graph_path.read_text())
                    for options in parameter_grid(config["operations"][operation]):
                        parameters = bind_parameters(operation, graph, options)
                        budget = {k: config[k] for k in ("timeout_seconds", "max_candidates", "max_output_items")}
                        for repetition in range(config["repeats"]):
                            for backend in backends:
                                if limit is not None and totals[operation] >= limit:
                                    break
                                comparison, pair, key = attempt_keys(implementation, operation, backend,
                                    graph_meta["snapshot_fingerprint"], parameters, budget, repetition)
                                if key in seen:
                                    continue
                                if code_hash() != frozen_code or implementation_hash() != implementation:
                                    raise ValueError("Benchmark code or native implementation changed during collection")
                                lock = None
                                try:
                                    if backend != "cpp":
                                        while lock is None:
                                            lock = GPULock.acquire(data_dir)
                                            if lock is None:
                                                await asyncio.sleep(1)
                                    job = dict(run_id=str(uuid4()), benchmark_id=identifier, benchmark_mode=mode,
                                        operation=operation, backend=backend, parameters=parameters, budget=budget,
                                        graph_path=str(graph_path), graph_id=spec["id"], graph_fingerprint=graph_meta["snapshot_fingerprint"],
                                        comparison_id=comparison, benchmark_pair_id=pair, benchmark_attempt_key=key,
                                        repetition=repetition, is_evaluation=is_evaluation, data_dir=str(data_dir),
                                        repository_root=str(ROOT), implementation_sha256=implementation,
                                        gpu_uuid=None if backend == "cpp" else gpu["uuid"], memory_safety=settings.backend_memory_safety)
                                    row = initial_row(job, graph, card, job["gpu_uuid"])
                                    row = await run_attempt(job, row, directory, python=arguments.python or sys.executable,
                                                            library=library, lock=lock)
                                finally:
                                    if lock:
                                        lock.close()
                                await publish(logger, row, directory)
                                rows.append(row)
                                seen.add(key)
                                totals[operation] += 1
                                print(f"{operation} {backend} {row['outcome']} {row['runtime_seconds']:.4f}s", flush=True)
                                atomic_json(directory / "status.json", dict(status="running", rows=len(rows), per_operation=dict(totals)))
                                if row.get("benchmark_cancelled"):
                                    raise asyncio.CancelledError()
            summary = summarize(rows, cards)
            summary.update(benchmark_id=identifier, mode=mode, implementation_sha256=implementation,
                           configured_graph_count=len(expand_graphs(config)),
                           prepared_graph_count=len(list((directory / "graphs").glob("*.metadata.json"))),
                           initial_examples_per_operation=None if arguments.full else config["bootstrap_examples_per_operation"],
                           global_bootstrap_counts=dict(totals), eligible_operations=len(cards))
            atomic_json(directory / "summary.json", summary)
            summary_table(directory, summary)
            atomic_json(directory / "status.json", dict(status="completed", rows=len(rows), per_operation=dict(totals)))
            print(json.dumps({k: summary[k] for k in ("benchmark_id", "mode", "rows", "evaluation_rows", "prepared_graph_count")}))
            return 0
        finally:
            logger.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--benchmark-id")
    parser.add_argument("--config", type=Path, default=ROOT / "benchmarks/backend_selection.json")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--native-library", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--instances", type=Path)
    parser.add_argument("--password-file", type=Path)
    parser.add_argument("--operations", nargs="+")
    parser.add_argument("--examples-per-operation", type=int, choices=(1, 2, 3))
    parser.add_argument("--full", action="store_true", help="explicitly run the complete grid instead of the small bootstrap")
    parser.add_argument("--is-evaluation", action="store_true", help="exclude this collection from all model training")
    args = parser.parse_args(argv)
    if args.child:
        return child(args.child)
    try:
        return asyncio.run(collect(args))
    except (ValueError, OSError, TimeoutError) as error:
        print("Benchmark stopped: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
