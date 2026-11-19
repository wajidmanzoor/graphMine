"""Run a scheduled, isolated GraphMine performance test on the real server."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import shutil
import subprocess
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from perf.common import ROOT, append, slug, timestamp, write_json, read_jsonl
from perf.monitor import proc_memory


CAPACITY = ("max_model_calls", "model_queue_seconds", "max_pending_jobs", "max_concurrent_uploads",
    "account_pending_jobs", "account_running_jobs", "account_job_seconds", "account_queue_seconds",
    "job_timeout_seconds", "analytics_cpu_workers", "analytics_gpu_uuids", "analytics_gpu_headroom_bytes",
    "analytics_llm_reserve_bytes", "analytics_max_input_bytes", "analytics_result_cache_bytes",
    "analytics_max_exports", "max_result_bytes", "database_pool_limit", "database_pool_size",
    "database_pool_wait_seconds", "database_pool_idle_seconds", "max_accounts", "account_storage_bytes",
    "account_upload_bytes", "max_upload_bytes", "llm_sleep_mode", "llm_sleep_level", "llm_idle_sleep_minutes",
    "llm_thinking_stages", "analytics_reasoning_effort", "analytics_thinking_token_budget",
    "analytics_route_thinking_token_budget", "llm_route_max_tokens", "llm_plan_max_tokens", "llm_analyst_max_tokens",
    "backend_selection", "backend_exploration_enabled", "backend_memory_safety", "capture_enabled",
    "llm_route_reasoning_effort","llm_plan_reasoning_effort","llm_analyst_reasoning_effort",
    "llm_enabled","allow_shared_gpu","graph_gpu_uuid","llm_gpu_uuid","result_summary_items",
    "backup_hours","backup_keep","retention_days","analytics_direct_plans",
    "backend_require_rollout_evidence","backend_exploration_budget","backend_max_explore_ratio","backend_min_timeout_seconds")


def safe_command(command):
    result, hide = [], False
    for arg in command:
        if hide:
            result.append("<redacted>")
            hide = False
        elif any(arg == key or arg.startswith(key+"=") for key in ("--api-key", "--token", "--hf-token", "--password")):
            if "=" in arg:
                result.append(arg.split("=",1)[0]+"=<redacted>")
            else:
                result.append(arg)
                hide = True
        else:
            result.append(arg)
    return result


def app_environment(args, run, overrides=None):
    from perf.accounts import backend_directory
    supplied = json.loads(args.app_env.read_text())
    supplied = supplied.get("env", supplied)
    env = {k: v for k,v in os.environ.items() if not k.startswith("GRAPHMINE_") and k not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update({k:str(v) for k,v in supplied.items()})
    env.update(overrides or {})
    private = run/"private"
    env.update({"PYTHONPATH": str(ROOT/"agent")+os.pathsep+str(ROOT/"python/graphmine"),
        "GRAPHMINE_REPO": str(ROOT), "GRAPHMINE_AGENT_DATA_ROOT": str(private/"data"),
        "GRAPHMINE_HISTORY_ROOT": str(private/"data/history"), "GRAPHMINE_CAPTURE_ROOT": str(private/"data/captures"),
        "GRAPHMINE_BACKUP_DIR": str(private/"backups"),
        "GRAPHMINE_API_HOST": "127.0.0.1", "GRAPHMINE_API_PORT": str(args.port),
        "GRAPHMINE_ACCOUNTS_ENABLED": "true", "GRAPHMINE_ACCOUNT_COOKIE_SECURE": "false",
        "GRAPHMINE_ACCOUNT_DAILY_TOKENS": "100000000", "GRAPHMINE_SERVER_DAILY_TOKENS": "10000000000",
        "GRAPHMINE_ACCOUNT_DAILY_JOBS": "100000", "GRAPHMINE_SERVER_DAILY_JOBS": "10000000",
        "GRAPHMINE_PERF_LOG": "1", "GRAPHMINE_PERF_DIR": str(run/"server"),
        "GRAPHMINE_BACKEND_DATA_DIR": str(backend_directory(run))})
    # Selecting backends still uses the existing trained models/evidence. Only
    # newly produced telemetry is written to the disposable store.
    for key in ("GRAPHMINE_TLS_CERTFILE", "GRAPHMINE_TLS_KEYFILE"):
        env.pop(key, None)
    return env


def settings_snapshot(python, env):
    code = "from dataclasses import asdict; from graphmine_agent.config import Settings; import json, importlib.metadata as m; s=Settings.from_env(); print(json.dumps({'settings':asdict(s),'packages':{k:m.version(k) for k in ['fastapi','uvicorn','httpx','pydantic']}},default=str))"
    return json.loads(subprocess.check_output([str(python), "-c", code], cwd=ROOT, env=env, text=True))


def stop(process, *, seconds=60):
    if process is not None and process.poll() is None:
        process.terminate()
        process.wait(timeout=seconds)


def wait_for_load(load, *, agent, monitor, timeout):
    deadline = time.monotonic() + timeout
    while True:
        for name, process in (("Test agent", agent), ("Resource monitor", monitor)):
            code = process.poll()
            if code is not None:
                raise RuntimeError(f"{name} exited during load generation (exit {code}); inspect its log")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(load.args, timeout)
        try:
            return load.wait(timeout=min(1, remaining))
        except subprocess.TimeoutExpired:
            pass


def sleep_model(client, host, headers, run):
    status = client.get(host+"/api/admin/llm/power", headers=headers)
    status.raise_for_status()
    if not status.json().get("enabled"):
        append(run/"run-events.jsonl", {"ts": timestamp(), "event": "sleep_unavailable"})
        return
    deadline = time.monotonic()+120
    while True:
        response = client.post(host+"/api/admin/llm/power/sleep", headers=headers, timeout=140)
        if response.status_code != 409 or time.monotonic() >= deadline:
            response.raise_for_status()
            assert response.json().get("sleeping") is True
            append(run/"run-events.jsonl", {"ts": timestamp(), "event": "model_asleep"})
            return
        time.sleep(2)


def cold_start(client, host, headers, run, llm_root, llm_key):
    status = client.get(host+"/api/admin/llm/power", headers=headers)
    status.raise_for_status()
    if status.json().get("enabled"):
        sleep_model(client, host, headers, run)
        return
    from perf.monitor import prometheus, provider_summary
    quiet_since, previous = None, None
    while quiet_since is None or time.monotonic()-quiet_since < 1800:
        response = client.get(llm_root+"/metrics", headers={"Authorization": "Bearer "+llm_key})
        response.raise_for_status()
        current = provider_summary(prometheus(response.text))
        counters = (current["prompt_tokens_total"], current["generation_tokens_total"])
        if None in counters or current["running"] is None or current["waiting"] is None:
            raise RuntimeError("Cannot verify 30 idle minutes: provider counters are unavailable")
        if current["running"] or current["waiting"] or previous is None or counters != previous:
            quiet_since = time.monotonic()
        append(run/"run-events.jsonl", {"ts": timestamp(), "event": "cold_idle_check", "provider": current,
                                      "quiet_seconds": time.monotonic()-quiet_since})
        previous = counters
        time.sleep(2)


def validate_generation(run, config):
    from collections import Counter
    shape = read_jsonl(run/"shape.jsonl")
    questions = read_jsonl(run/"questions.jsonl")
    if config.get("locust_exit_code") not in {0,1}:
        raise RuntimeError("Locust did not exit normally")
    if config["test"] == "benchmark":
        import yaml
        expected = {q["id"]:5 for q in yaml.safe_load((ROOT/"perf/questions.yaml").read_text())["questions"]}
        if config.get("preflight"):
            expected = {key:1 for key in expected}
        actual = Counter(q["question_id"] for q in questions if q.get("question_sent_at"))
        if dict(actual) != expected:
            raise RuntimeError("Benchmark did not send each of the six questions five times")
    elif config["test"] in {"load","spike","soak"}:
        if max((r["users"] for r in shape),default=0) != config["requested_users"]:
            raise RuntimeError("The load generator did not reach the requested number of users")
        if max((r["elapsed_seconds"] for r in shape),default=0) < config["duration_seconds"]-2:
            raise RuntimeError("The load generator stopped before the requested duration")
    if not questions or not read_jsonl(run/"system.jsonl"):
        raise RuntimeError("The run has no completed question records or system samples")


def run_one(args, *, overrides=None, matrix_row=None):
    import httpx
    import yaml
    dataset = yaml.safe_load((ROOT/"perf/questions.yaml").read_text())["dataset"]
    label = slug(args.label)
    run = (args.output/(time.strftime("%Y%m%dT%H%M%S", time.gmtime())+"-"+label)).resolve()
    run.mkdir(parents=True, exist_ok=False, mode=0o700)
    private = run/"private"
    private.mkdir(mode=0o700)
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        probe.bind(("127.0.0.1", args.port))
    env = app_environment(args, run, overrides)
    original = settings_snapshot(args.app_python, {**env, **{k:str(v) for k,v in json.loads(args.app_env.read_text()).get("env", json.loads(args.app_env.read_text())).items()}})
    snapshot = settings_snapshot(args.app_python, env)
    settings = snapshot["settings"]
    assert Path(settings["data_root"]) == private/"data"
    vllm_pid = int(subprocess.check_output(["systemctl", "--user", "show", args.vllm_service, "--property=MainPID", "--value"], text=True).strip())
    if not vllm_pid:
        raise RuntimeError("The configured vLLM service is not running")
    vllm_command = Path(f"/proc/{vllm_pid}/cmdline").read_bytes().decode().strip("\0").split("\0")
    gpu_names = subprocess.check_output(["nvidia-smi", "--query-gpu=index,uuid,name,memory.total", "--format=csv"], text=True).strip()
    config = {"test": args.test, "label": label, "run_id": run.name, "prepared_at": timestamp(),
        "lab_window": args.lab_window, "matrix_row": matrix_row, "preflight":args.preflight,
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT)),
        "capacity": {"GRAPHMINE_"+k.upper(): settings[k] for k in CAPACITY},
        "baseline_capacity": {"GRAPHMINE_"+k.upper(): original["settings"][k] for k in CAPACITY},
        "test_quota_overrides": {k:v for k,v in env.items() if "DAILY_TOKENS" in k or "DAILY_JOBS" in k},
        "uvicorn_limit_concurrency": 256, "model_calls_per_user":1, "planning_slots":8,
        "planning_slots_per_user":1, "running_jobs_per_user":1, "planning_deadline_seconds":360,
        "vllm_command": safe_command(vllm_command),
        "model": settings["llm_model"], "router_model": settings["analytics_router_model"] or settings["llm_model"],
        "planner_model": settings["analytics_planner_model"] or settings["llm_model"],
        "analyst_model": settings["analytics_answer_model"] or settings["llm_model"],
        "legacy_planner_adapter":settings["llm_planner_model"],"legacy_analyst_adapter":settings["llm_analyst_model"],
        "gpu_names": gpu_names, "free_ram_bytes": proc_memory()["MemAvailable"],
        "app_packages": snapshot["packages"], "app_python": str(args.app_python),
        "source_id": args.source_id, "query": args.query or dataset["query"],
        "projection":args.projection or ("elements" if args.query else dataset["projection"]),
        "dataset_description":dataset["description"] if not args.query else "Explicit custom query", "seed": args.seed,
        "requested_users": {"benchmark":1,"load":10,"stress":50,"spike":20,"soak":5}[args.test],
        "duration_seconds": {"benchmark":None,"load":1200,"stress":3000,"spike":600,"soak":7200}[args.test]}
    write_json(run/"config.json", config)
    write_json(private/"app-env.json", {k:v for k,v in env.items() if k.startswith("GRAPHMINE_")}, private=True)
    agent = monitor = load = None
    authenticated = False
    host = f"http://127.0.0.1:{args.port}"
    client = httpx.Client(timeout=30, trust_env=False)
    streams, headers = [], {}
    failure = None
    try:
        subprocess.run([str(args.app_python), str(ROOT/"perf/accounts.py"), "create", str(run)], cwd=ROOT, env=env, check=True)
        # Preserve the installed bandit's history and exploration budget in an
        # independent copy. Test attempts must not train/change the live ledger.
        backend_source = Path(original["settings"]["backend_data_dir"])
        backend_copy = Path(settings["backend_data_dir"])
        if backend_source.exists():
            shutil.copytree(backend_source, backend_copy, symlinks=False,dirs_exist_ok=True)
            config["backend_history_copied"] = True
        else:
            config["backend_history_copied"] = False
        manifest = json.loads((private/"accounts.json").read_text())
        admin = next(a for a in manifest["accounts"] if a["username"] == "perftest_admin")
        stream = (run/"agent.log").open("w"); streams.append(stream)
        agent = subprocess.Popen([str(args.app_python), "-m", "graphmine_agent", "serve"], cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        manifest["agent_pid"] = agent.pid
        write_json(private/"accounts.json", manifest, private=True)
        deadline = time.monotonic()+120
        while True:
            if agent.poll() is not None:
                raise RuntimeError("Test agent exited during startup; inspect agent.log")
            try:
                response = client.get(host+"/api/build")
                response.raise_for_status()
                break
            except httpx.HTTPError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.5)
        response = client.post(host+"/api/auth/login", headers={"X-GraphMine-Request":"1"},
            json={"username":admin["username"], "password":admin["password"], "issue_token":True})
        response.raise_for_status()
        headers = {"Authorization":"Bearer "+response.json()["access_token"], "X-Perf-Run-ID":run.name}
        authenticated = True
        response = client.get(host+"/api/admin/perf/snapshot", headers=headers)
        response.raise_for_status()
        llm_root = settings["llm_base_url"].rstrip("/").removesuffix("/v1")
        write_json(private/"monitor.json", {"run_id":run.name,"host":host,"admin_token":headers["Authorization"][7:],
            "llm_root":llm_root,"llm_api_key":settings["llm_api_key"],"data_root":settings["data_root"],
            "pids":{"agent":agent.pid,"vllm":vllm_pid}}, private=True)
        write_json(private/"locust.json", {**{k:config[k] for k in ("test","run_id","seed","source_id","query","projection","preflight")},
            "host":host,"accounts":[a for a in manifest["accounts"] if a["username"] != "perftest_admin"]}, private=True)
        stream = (run/"monitor.log").open("w"); streams.append(stream)
        monitor = subprocess.Popen([sys.executable, str(ROOT/"perf/monitor.py"), str(run)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        if args.test == "spike":
            cold_start(client, host, headers, run, llm_root, settings["llm_api_key"])
        config.update(started_at=timestamp(), agent_pid=agent.pid, vllm_pid=vllm_pid)
        write_json(run/"config.json", config)
        append(run/"run-events.jsonl", {"ts":timestamp(),"event":"load_generation_started"})
        stream = (run/"locust.log").open("w"); streams.append(stream)
        load = subprocess.Popen([sys.executable, "-m", "locust", "-f", str(ROOT/"perf/locustfile.py"),
            "--headless", "--only-summary", "--stop-timeout", "2400", "--csv", str(run/"locust"),
            "--html", str(run/"locust.html")], cwd=ROOT, env={**os.environ, "GRAPHMINE_PERF_RUN_DIR":str(run)},
            stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        print(json.dumps({"run":str(run),"agent_pid":agent.pid,"monitor_pid":monitor.pid,"locust_pid":load.pid}), flush=True)
        # A benchmark must finish all thirty questions, including failed ones.
        # This guard diagnoses a broken generator/login instead of hanging forever.
        wait_for_load(load, agent=agent, monitor=monitor,
                      timeout=21600 if args.test == "benchmark" else config["duration_seconds"]+2700)
        config.update(finished_at=timestamp(), locust_exit_code=load.returncode)
        validate_generation(run,config)
    except BaseException as exc:
        failure = exc
        config.update(finished_at=timestamp(), infrastructure_error=f"{type(exc).__name__}: {exc}")
    finally:
        for process in (load,):
            try:
                stop(process)
            except Exception as exc:
                config["stop_error"] = str(exc)
                failure = failure or exc
        if authenticated and agent is not None and agent.poll() is None:
            try:
                sleep_model(client, host, headers, run)
            except Exception as exc:
                config["sleep_error"] = str(exc)
                failure = failure or exc
        for process in (monitor, agent):
            try:
                stop(process)
            except Exception as exc:
                config["stop_error"] = str(exc)
                failure = failure or exc
        for stream in streams:
            stream.close()
        client.close()
        with (run/"events.jsonl").open("wb") as combined:
            for path in sorted((run/"server").glob("events-*.jsonl")):
                combined.write(path.read_bytes())
        if (private/"accounts.json").exists() and (agent is None or agent.poll() is not None):
            try:
                from perf.accounts import cleanup
                cleanup(run)
            except Exception as exc:
                config["cleanup_error"] = str(exc)
                failure = failure or exc
        write_json(run/"config.json", config)
        from perf.report import generate
        generate(run)
    if failure:
        raise RuntimeError(f"Run retained at {run}: {failure}") from failure
    return run


def main():
    def interrupted(*_):
        raise KeyboardInterrupt("Performance run interrupted")
    signal.signal(signal.SIGTERM,interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("test", choices=["benchmark","load","stress","spike","soak"])
    parser.add_argument("--label", required=True)
    parser.add_argument("--app-env", type=Path, required=True, help="Private JSON object of installed GRAPHMINE_* environment settings")
    parser.add_argument("--app-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--output", type=Path, default=ROOT/"var/perf")
    parser.add_argument("--port", type=int, default=18003)
    parser.add_argument("--vllm-service", default="graphmine-vllm.service")
    parser.add_argument("--source-id")
    parser.add_argument("--query", help="Default: the Yelp User–Business projection in perf/questions.yaml")
    parser.add_argument("--projection", choices=["elements","rows"],help="Default rows for the suite query, elements for a custom query")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--lab-window", default=os.getenv("GRAPHMINE_PERF_LAB_WINDOW"), help="Record the agreed lab time slot")
    parser.add_argument("--confirm-shared-gpu", action="store_true")
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--preflight",action="store_true",help="Diagnostic only: one journey per question type")
    parser.add_argument("--vllm-env-file", type=Path)
    args = parser.parse_args()
    if args.preflight and (args.test != "benchmark" or args.matrix):
        parser.error("--preflight is only available for a standalone benchmark diagnostic")
    if not args.lab_window:
        parser.error("Record the agreed lab slot with --lab-window or GRAPHMINE_PERF_LAB_WINDOW")
    if args.test in {"stress","soak"} and not args.confirm_shared_gpu:
        parser.error("Stress and soak require --confirm-shared-gpu in the agreed lab window")
    if args.matrix:
        if args.test != "load" or not args.vllm_env_file:
            parser.error("--matrix requires load and --vllm-env-file")
        from perf.matrix import run_matrix
        run_matrix(args)
    else:
        print(run_one(args), flush=True)


if __name__ == "__main__":
    main()
