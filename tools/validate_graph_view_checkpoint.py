#!/usr/bin/env python3
"""Run the required CPU migration gates and retain evidence for one small commit.

Uses existing C++ oracles, Python binding/native tests and actual agent capability
checks. No GPU build, service restart, deployment or production-path mutation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.validate_native_runtime import validate


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--agent-python", type=Path, required=True)
    parser.add_argument("--completed-ctest", action="store_true")
    args = parser.parse_args()
    build, output = args.build.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, CUDA_VISIBLE_DEVICES="", OPENBLAS_NUM_THREADS="1",
                       OMP_NUM_THREADS="2", PYTHONPATH=str(ROOT / "python/graphmine"),
                       GRAPHMINE_NATIVE_CPU_BUILD=str(build), GRAPHMINE_NATIVE_GPU_BUILD=str(build),
                       GRAPHMINE_NATIVE_ORIGINAL_BUILD=str(build),
                       GRAPHMINE_NATIVE_LIBRARY=str(build / "libgraphmine_runtime.so"))
    binary_before = sha(build / "libgraphmine_runtime.so")

    def run(name, command, env=environment):
        with (output / (name + ".log")).open("w") as log:
            subprocess.run(list(map(str, command)), cwd=ROOT, env=env, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        print(name + ": passed", flush=True)

    def pytest(name, paths, *, executable=args.python, extra=(), env=environment):
        run(name, [executable, "-m", "pytest", "-q", *paths, *extra,
                   "--junitxml=" + str(output / (name + ".xml"))], env)

    if not args.completed_ctest:
        run("ctest", ["ctest", "--test-dir", build, "--output-on-failure", "-j", "4",
                      "--output-junit", output / "ctest.xml"])
    else:
        assert (output / "ctest.xml").is_file()
    # The existing runner snapshots source files and binaries around execution.
    validate(build, "cpu", 0, output)
    pytest("native-cpu", ["library/tests/test_native_" + name + ".py" for name in
                         ("extended", "learning", "record_queries", "application_contracts", "table_projection")])
    pytest("native-original-cpu", ["library/tests/test_native_original_gpu.py"],
           env=dict(environment, GRAPHMINE_EVIDENCE_DEVICE="cpu"))
    pytest("python-bindings-cpu", ["library/tests/test_native_binding.py"], extra=["-k",
           "not gpu and not cuda and not cudf and not device and not graphset and not gamma "
           "and not native_betweenness_backends and not native_betweenness_path_overflow "
           "and not ecl-maxflow and not hungarian-cuda"])
    pytest("evidence-gate", ["python/graphmine/tests/test_native_evidence.py"],
           executable=args.agent_python, extra=["-c", "python/graphmine/pyproject.toml"])
    run("evidence-build", [sys.executable, "tools/build_native_execution_evidence.py", "--build", build,
                          "--reports", output, "--junit", output / "native-cpu.xml",
                          "--junit", output / "native-original-cpu.xml"])
    agent_env = dict(environment, PYTHONPATH=str(ROOT / "python/graphmine") + ":" + str(ROOT / "agent"),
                     GRAPHMINE_RUNTIME_REPOSITORY=str(ROOT), GRAPHMINE_ANALYTICS_PYTHON=str(args.python.absolute()))
    pytest("agent-capabilities", [
        "agent/tests/test_analytics_workflows.py::test_live_capabilities_authorization_and_input_scope",
        "agent/tests/test_analytics_workflows.py::test_capabilities_share_one_verification_until_evidence_changes",
        "agent/tests/test_analytics_scheduler.py::test_workflow_admission_uses_verified_backends_and_explicit_devices"],
        executable=args.agent_python, extra=["-c", "agent/pyproject.toml"], env=agent_env)
    report = output / "admission.json"
    code = "from pathlib import Path; from graphmine.evidence import capabilities; import json; " \
           "print(json.dumps(capabilities(Path.cwd()), indent=2))"
    with report.open("w") as stream:
        subprocess.run([args.python, "-c", code], env=environment, cwd=ROOT, stdout=stream, check=True)
    admission = json.loads(report.read_text())
    assert not admission["verification_issues"], admission["verification_issues"]
    admitted = [op["id"] for op in admission["problems"]
                if any(b["id"] == "cpp" and b["verified"] for b in op["backends"])]
    assert len(admitted) == 82, admitted
    assert sha(build / "libgraphmine_runtime.so") == binary_before
    tests = {}
    for name in ("ctest", "native-cpu", "native-original-cpu", "python-bindings-cpu", "evidence-gate", "agent-capabilities"):
        document = ET.parse(output / (name + ".xml")).getroot()
        assert not document.findall(".//failure") and not document.findall(".//error"), name
        tests[name] = len(document.findall(".//testcase"))
    summary = {"implementation_sha256": admission["implementation_sha256"], "binary_sha256": binary_before,
               "tests": tests, "admitted_cpp_problems": admitted, "verification_issues": [],
               "runner_sha256": sha(Path(__file__)), "production_changed": False}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"tests": tests, "admitted_cpp": len(admitted)}), flush=True)


if __name__ == "__main__":
    main()
