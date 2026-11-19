"""Sequential load comparisons with byte-for-byte restoration of vLLM settings."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import html
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

import yaml

from perf.common import ROOT, slug, timestamp, write_json
from perf.report import analyze, comparisons, generate, table


def updated_environment(original, overrides):
    text = original.decode()
    for key,value in overrides.items():
        if not re.fullmatch(r"GRAPHMINE_[A-Z0-9_]+",key) or not re.fullmatch(r"[A-Za-z0-9_,.:-]+",str(value)):
            raise ValueError("Unsafe matrix environment assignment")
        pattern = re.compile(r"^(?:export\s+)?"+re.escape(key)+r"=.*$",re.M)
        text = pattern.sub("",text)
        text += f"\n{key}={value}\n"
    return text.encode()


def replace_file(path, contents, mode):
    temporary = path.with_name(path.name+".graphmine-perf.tmp")
    with temporary.open("wb") as stream:
        os.chmod(temporary,mode)
        stream.write(contents)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


@contextmanager
def restored_environment(path, backup):
    if path.is_symlink():
        raise ValueError("Use the real vLLM environment path, not a symlink")
    original, mode = path.read_bytes(), path.stat().st_mode & 0o777
    backup.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    replace_file(backup,original,0o600)
    try:
        yield original,mode
    finally:
        replace_file(path,original,mode)


def restart(args, llm):
    import httpx
    subprocess.run(["systemctl","--user","restart",args.vllm_service],check=True,timeout=900)
    deadline = time.monotonic()+600
    with httpx.Client(timeout=5,trust_env=False) as client:
        while True:
            try:
                response = client.get(llm["root"]+"/health",headers={"Authorization":"Bearer "+llm["key"]})
                response.raise_for_status()
                return
            except httpx.HTTPError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(2)


def restore_sleep(args):
    # Reuse the app's cross-process leases: never sleep underneath another call.
    code = """import asyncio,json,os,sys
raw=json.load(open(sys.argv[1])); os.environ.update(raw.get('env',raw))
from graphmine_agent.config import Settings
from graphmine_agent.llm_power import LLMPowerRegistry
async def run():
    registry=LLMPowerRegistry(Settings.from_env())
    try:
        power=registry.for_url()
        if power.enabled:
            await power.sleep_now()
    finally:
        await registry.close()
asyncio.run(run())
"""
    subprocess.run([str(args.app_python),"-c",code,str(args.app_env)],check=True,timeout=180,
                   cwd=ROOT,env={**os.environ,"PYTHONPATH":str(ROOT/"agent")})


def run_matrix(args):
    from perf.run import app_environment,run_one,settings_snapshot
    root = (args.output/(time.strftime("%Y%m%dT%H%M%S",time.gmtime())+"-"+slug(args.label)+"-matrix")).resolve()
    root.mkdir(parents=True,mode=0o700)
    rows = yaml.safe_load((ROOT/"perf/matrix.yaml").read_text())["rows"]
    settings = settings_snapshot(args.app_python,app_environment(args,root))["settings"]
    llm = {"root":settings["llm_base_url"].rstrip("/").removesuffix("/v1"),"key":settings["llm_api_key"]}
    paths, changed = [], False
    record = {"started_at":timestamp(),"rows":rows,"runs":[],"restored":False}
    def interrupted(*_):
        raise KeyboardInterrupt("Matrix interrupted; restoring original settings")
    handlers = {s:signal.signal(s,interrupted) for s in (signal.SIGINT,signal.SIGTERM)}
    lock = (args.output/"matrix.lock").open("a")
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with restored_environment(args.vllm_env_file,root/"private/vllm-env.original") as (original,mode):
            try:
                for row in rows:
                    changed = True
                    replace_file(args.vllm_env_file,updated_environment(original,row["vllm"]),mode)
                    restart(args,llm)
                    one = argparse.Namespace(**vars(args))
                    one.label = args.label+"-"+row["label"]
                    one.output = root
                    path = run_one(one,overrides=row["app"],matrix_row=row)
                    paths.append(path)
                    record["runs"].append(str(path))
                    write_json(root/"matrix.json",record)
            finally:
                # Restore before restarting, including failures within a row.
                replace_file(args.vllm_env_file,original,mode)
                if changed:
                    restart(args,llm)
                    restore_sleep(args)
                record["restored"] = True
    finally:
        record["finished_at"] = timestamp()
        write_json(root/"matrix.json",record)
        lock.close()
        for s,handler in handlers.items():
            signal.signal(s,handler)
        if record["restored"]:
            (root/"private/vllm-env.original").unlink(missing_ok=True)
    if paths:
        baseline = analyze(paths[0])
        comparisons_all = []
        for path in paths:
            current = generate(path,paths[0])
            comparisons_all.extend({"run":path.name,**r} for r in comparisons(current["headline"],baseline["headline"]))
        md,body = table(comparisons_all)
        (root/"report.md").write_text("# GraphMine load matrix\n\n"+md+"\n"+"\n".join(f"- [{p.name}]({p.name}/report.html)" for p in paths))
        (root/"report.html").write_text("<!doctype html><meta charset='utf-8'><title>GraphMine load matrix</title><style>body{font:16px system-ui;margin:30px}td,th{padding:8px;border-bottom:1px solid #ccc}.good{color:green}.bad{color:#b00}</style><h1>GraphMine load matrix</h1>"+body+"<script>document.querySelectorAll('td').forEach(c=>{if(c.textContent==='improved')c.className='good';if(c.textContent==='regressed')c.className='bad'})</script>")
    print(root,flush=True)
