"""Sample real provider, device, host and app counters every two seconds."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from perf.common import append, timestamp


def prometheus(text):
    result = []
    pattern = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+([^\s]+)(?:\s+.*)?$')
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            continue
        name, raw, value = match.groups()
        try:
            number = float(value)
            labels = {key: json.loads('"'+encoded+'"') for key, encoded in
                      re.findall(r'(\w+)="((?:\\.|[^"\\])*)"', raw or "")}
        except (ValueError, json.JSONDecodeError):
            continue
        result.append({"name": name, "labels": labels, "value": number if math.isfinite(number) else None})
    return result


def provider_summary(samples, previous=None, interval=None):
    def values(*names):
        return [r["value"] for r in samples if r["name"].split(":")[-1] in names and r["value"] is not None]
    def total(*names):
        found = values(*names)
        return sum(found) if found else None
    cache = values("gpu_cache_usage_perc", "kv_cache_usage_perc")
    result = {"running": total("num_requests_running"), "waiting": total("num_requests_waiting"),
              "kv_cache_percent": sum(cache)/len(cache)*100 if cache else None,
              "preemptions_total": total("num_preemptions_total"),
              "prompt_tokens_total": total("prompt_tokens_total"),
              "generation_tokens_total": total("generation_tokens_total")}
    for key in ("prompt", "generation"):
        current = result[key+"_tokens_total"]
        before = (previous or {}).get(key+"_tokens_total")
        result[key+"_tokens_per_second"] = (current-before)/interval if interval and current is not None and before is not None and current >= before else None
    return result


def proc_memory():
    return {line.split(":")[0]: int(line.split()[1])*1024 for line in Path("/proc/meminfo").read_text().splitlines()}


def proc_cpu():
    fields = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    # Guest ticks are already part of user/nice; do not count them twice.
    return sum(fields[:8]), fields[3]+fields[4]


def disk_counters():
    disks = {p.name for p in Path("/sys/block").iterdir() if (p/"device").exists()}
    read = write = 0
    for line in Path("/proc/diskstats").read_text().splitlines():
        row = line.split()
        if row[2] in disks:
            read += int(row[5])*512
            write += int(row[9])*512
    return {"read_bytes": read, "write_bytes": write}


def processes(roots):
    rows = {}
    for path in Path("/proc").glob("[0-9]*/status"):
        try:
            info = dict(line.split(":", 1) for line in path.read_text().splitlines())
            rows[int(path.parent.name)] = {"pid": int(path.parent.name), "parent": int(info["PPid"]),
                "name": info["Name"].strip(), "rss_bytes": int(info.get("VmRSS", "0 kB").split()[0])*1024}
        except (OSError, ValueError, KeyError):
            continue
    result = {}
    for name, pid in roots.items():
        selected = {int(pid)} if pid else set()
        while True:
            expanded = selected | {p for p, row in rows.items() if row["parent"] in selected}
            if expanded == selected:
                break
            selected = expanded
        found = [rows[p] for p in sorted(selected) if p in rows]
        result[name] = {"root_pid": pid, "root_rss_bytes": rows.get(int(pid or 0), {}).get("rss_bytes"),
                       "tree_rss_bytes": sum(r["rss_bytes"] for r in found) if found else None,
                       "processes": found}
    return result


def gpus():
    output = subprocess.check_output(["nvidia-smi", "--query-gpu=index,uuid,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw", "--format=csv,noheader,nounits"], timeout=5, stderr=subprocess.DEVNULL, text=True)
    names = ["index", "uuid", "utilization_percent", "memory_used_mb", "memory_total_mb", "temperature_c", "power_watts"]
    result = []
    for values in csv.reader(output.splitlines()):
        row = {}
        for key, value in zip(names, values):
            try:
                row[key] = value.strip() if key == "uuid" else float(value)
            except ValueError:
                row[key] = None
        result.append(row)
    return result


def sqlite_size(root):
    total = 0
    for path in Path(root).rglob("*"):
        if not str(path).endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm")):
            continue
        try:
            info = path.stat()
        except FileNotFoundError:
            # SQLite can remove a WAL/SHM file during a checkpoint. There is
            # no file to count, and this normal race must not stop telemetry.
            continue
        if stat.S_ISREG(info.st_mode):
            total += info.st_size
    return total


class Monitor:
    def __init__(self, config):
        import httpx
        self.config = config
        self.client = httpx.Client(timeout=5, trust_env=False, verify=config.get("verify_tls", True))
        self.previous_cpu = self.previous_disk = self.previous_provider = self.previous_time = None

    def sample(self):
        now = time.monotonic()
        interval = now-self.previous_time if self.previous_time else None
        row = {"ts": timestamp(), "interval_seconds": interval, "errors": []}
        for key, fn in (("gpu", gpus), ("processes", lambda: processes(self.config.get("pids", {})))):
            try:
                row[key] = fn()
            except Exception as exc:
                row[key] = None
                row["errors"].append({"component": key, "message": str(exc)[:500]})
        try:
            cpu, mem, disk = proc_cpu(), proc_memory(), disk_counters()
            cpu_percent = None
            if self.previous_cpu and cpu[0] > self.previous_cpu[0]:
                cpu_percent = 100*(1-(cpu[1]-self.previous_cpu[1])/(cpu[0]-self.previous_cpu[0]))
            row["host"] = {"cpu_percent": cpu_percent, "ram_total_bytes": mem["MemTotal"],
                "ram_available_bytes": mem["MemAvailable"], "ram_used_bytes": mem["MemTotal"]-mem["MemAvailable"],
                "swap_total_bytes": mem["SwapTotal"], "swap_used_bytes": mem["SwapTotal"]-mem["SwapFree"],
                "disk": {**disk, **{k+"_per_second": (v-self.previous_disk[k])/interval if self.previous_disk and interval else None for k,v in disk.items()}}}
            self.previous_cpu, self.previous_disk = cpu, disk
        except Exception as exc:
            row["errors"].append({"component": "host", "message": str(exc)[:500]})
        try:
            response = self.client.get(self.config["llm_root"].rstrip("/")+"/metrics", headers={"Authorization": "Bearer "+self.config["llm_api_key"]})
            response.raise_for_status()
            samples = prometheus(response.text)
            row["vllm"] = provider_summary(samples, self.previous_provider, interval)
            row["vllm"]["histograms"] = [r for r in samples if any(x in r["name"] for x in ("time_to_first_token", "e2e_request_latency"))]
            self.previous_provider = row["vllm"]
        except Exception as exc:
            row["vllm"] = None
            row["errors"].append({"component": "vllm", "message": str(exc)[:500]})
        try:
            response = self.client.get(self.config["host"].rstrip("/")+"/api/admin/perf/snapshot", headers={
                "Authorization": "Bearer "+self.config["admin_token"], "X-Perf-Run-ID": self.config["run_id"]})
            response.raise_for_status()
            row["app"] = response.json()
        except Exception as exc:
            row["app"] = None
            row["errors"].append({"component": "app", "message": str(exc)[:500]})
        try:
            row["sqlite_bytes"] = sqlite_size(self.config["data_root"])
        except OSError as exc:
            row["sqlite_bytes"] = None
            row["errors"].append({"component": "sqlite", "message": str(exc)[:500]})
        self.previous_time = now
        return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--interval", type=float, default=2)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("interval must be positive")
    config = json.loads((args.run/"private/monitor.json").read_text())
    monitor, stopped = Monitor(config), False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopped:
            started = time.monotonic()
            append(args.run/"system.jsonl", monitor.sample())
            time.sleep(max(0, args.interval-(time.monotonic()-started)))
    finally:
        monitor.client.close()


if __name__ == "__main__":
    main()
