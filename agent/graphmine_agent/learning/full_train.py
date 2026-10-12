"""Wait for verified data, then prepare and train both larger-cycle adapters."""

from __future__ import annotations

import argparse
import csv
import fcntl
import io
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from ..history import HistoryStore
from ..models import utc_now

GPUS = {
    "planner": "GPU-177a4150-e6ff-62d9-810f-166fe6a4575b",
    "analyst": "GPU-f9f2c156-0de4-a1f3-0c8a-a77ca24d10f7",
}


def write_status(root, phase, **details):
    record = {
        "phase": phase,
        "pid": os.getpid(),
        "updated_at": utc_now().isoformat(),
        **details,
    }
    HistoryStore.write(root / "training-cycle-status.json", record)
    print(json.dumps(record), flush=True)


def require_free_gpu(gpu):
    raw = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=uuid,memory.free", "--format=csv,noheader,nounits"],
        text=True,
    )
    free = {row[0].strip(): int(row[1].strip()) for row in csv.reader(io.StringIO(raw))}
    if free.get(gpu, 0) < 42000:
        raise RuntimeError(
            "Training GPU is not free; no existing process was stopped: " + gpu
        )


def run(root, data_unit):
    policy_path = root / "collection-policy.json"
    if policy_path.exists() and not json.loads(policy_path.read_text()).get(
        "automatic_training", True
    ):
        raise RuntimeError(
            "Training is disabled by the user's data-only collection policy"
        )
    repo = Path(__file__).resolve().parents[3]
    while True:
        state_path = root / "data-cycle-status.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        if state.get("phase") == "data_ready_for_training":
            break
        process = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                data_unit,
                "-p",
                "ActiveState",
                "-p",
                "MainPID",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        observed = dict(
            line.split("=", 1) for line in process.stdout.splitlines() if "=" in line
        )
        if (
            observed.get("ActiveState") != "active"
            or int(observed.get("MainPID", "0")) <= 0
        ):
            raise RuntimeError(
                "Data generation stopped before the dataset was ready; saved data is preserved"
            )
        write_status(
            root,
            "waiting_for_verified_data",
            data_phase=state.get("phase"),
            observed_data_pid=int(observed["MainPID"]),
            data_unit=data_unit,
        )
        time.sleep(30)
    if shutil.disk_usage(root).free < 20 * 1024**3:
        raise RuntimeError("At least 20 GiB free space is required before training")
    checkpoint = (
        repo
        / ".graphmine-learning/training-model-cache/models--Qwen--Qwen3.8-27B/snapshots/1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
    )
    interpreter = repo / ".venv-training/bin/python"
    environment = dict(os.environ)
    environment.update(
        PYTHONPATH=str(repo / "agent"),
        HF_HUB_OFFLINE="1",
        CUDA_DEVICE_ORDER="PCI_BUS_ID",
        PYTHONUNBUFFERED="1",
        PYTORCH_ALLOC_CONF="expandable_segments:True",
    )
    compatibility = str(repo / ".cuda-compat-13-0/usr/local/cuda-13.0/compat")
    environment["LD_LIBRARY_PATH"] = compatibility + (
        ":" + environment["LD_LIBRARY_PATH"]
        if environment.get("LD_LIBRARY_PATH")
        else ""
    )
    processes, logs = {}, []
    try:
        # Tokenize and validate both immutable datasets before either optimizer starts.
        for adapter, gpu in GPUS.items():
            dataset = root / (adapter + "-dataset-v1")
            training = root / (adapter + "-training-v1")
            if not (training / "run.json").exists():
                write_status(root, "preparing_training", adapter=adapter)
                with (root / (adapter + "-prepare.log")).open("a") as log:
                    subprocess.run(
                        [
                            str(interpreter),
                            "-m",
                            "graphmine_agent.learning.dual_finetune",
                            "prepare",
                            str(dataset),
                            "--checkpoint",
                            str(checkpoint),
                            "--output",
                            str(training),
                            "--gpu",
                            gpu,
                            "--max-length",
                            "16384",
                            "--epochs",
                            "2",
                        ],
                        cwd=repo,
                        env={**environment, "CUDA_VISIBLE_DEVICES": gpu},
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=True,
                    )
        for gpu in GPUS.values():
            require_free_gpu(gpu)
        for adapter, gpu in GPUS.items():
            training = root / (adapter + "-training-v1")
            state_path = training / "status.json"
            prior = json.loads(state_path.read_text()) if state_path.exists() else {}
            if prior.get("phase") == "completed":
                continue
            arguments = [
                str(interpreter),
                "-m",
                "graphmine_agent.learning.dual_finetune",
                "train",
                str(training),
                "--execute",
            ]
            if (training / "checkpoints").exists():
                checkpoints = sorted(
                    (training / "checkpoints").glob("checkpoint-*"),
                    key=lambda p: int(p.name.rsplit("-", 1)[1]),
                )
                checkpoints = [
                    p
                    for p in checkpoints
                    if (p / "trainer_state.json").is_file()
                    and (p / "optimizer.pt").is_file()
                ]
                if not checkpoints:
                    raise RuntimeError(
                        "Existing training output has no complete resumable checkpoint: "
                        + adapter
                    )
                arguments += ["--resume", str(checkpoints[-1])]
            log = (root / (adapter + "-training.log")).open("a")
            logs.append(log)
            processes[adapter] = subprocess.Popen(
                arguments,
                cwd=repo,
                env={**environment, "CUDA_VISIBLE_DEVICES": gpu},
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        while any(process.poll() is None for process in processes.values()):
            write_status(
                root,
                "training",
                processes={
                    name: {"pid": p.pid, "exit_code": p.poll(), "gpu": GPUS[name]}
                    for name, p in processes.items()
                },
            )
            time.sleep(30)
        failed = {
            name: p.returncode for name, p in processes.items() if p.returncode != 0
        }
        if failed:
            raise RuntimeError(
                "Training process failed; checkpoints are preserved: "
                + json.dumps(failed)
            )
        for adapter in GPUS:
            final = json.loads(
                (root / (adapter + "-training-v1") / "status.json").read_text()
            )
            if (
                final.get("phase") != "completed"
                or final["global_step"] != final["planned_steps"]
            ):
                raise RuntimeError(
                    "Training did not complete its prepared steps: " + adapter
                )
        write_status(
            root,
            "trained_awaiting_weight_verification_and_evaluation",
            adapters=list(GPUS),
        )
    finally:
        for log in logs:
            log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--data-unit", default="graphmine-full-data-v1.service")
    args = parser.parse_args()
    root = args.root.resolve()
    with (root / ".training-cycle.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            run(root, args.data_unit)
        except Exception as error:
            write_status(
                root, "failed", error_type=type(error).__name__, error=str(error)
            )
            raise


if __name__ == "__main__":
    main()
