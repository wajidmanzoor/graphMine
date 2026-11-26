# Deferred GPU revalidation — 2026-11-26

The user authorized this exception: “lets document the check for latter and for
now push to prd”. Another user's benchmark occupied approximately 43 GiB of
physical analytics GPU 1. It was not stopped or changed. The queued rerun was
cancelled; there is no automatic background rerun.

Fresh validation completed 170,599 native oracle requests in 23 reports and
175 CPU contract tests. GAMMA's fixed-clique oracle then ran out of GPU memory
after 46 requests. The separate GPU contract run passed 33 tests and failed one
MBE-GPU test because of insufficient GPU memory. These are incomplete reruns,
not passing GPU validation. The failed reports and logs are retained privately
under graphmine-data/environments/state/iu-neo4j-20261126/native-contention.

These checks remain outstanding:

- GAMMA: contracts, fixed-clique oracle and boundaries.
- KCGPU: contracts, fixed-clique oracle and boundaries.
- KCore-GPU and libcugraph: core oracles, contracts and boundaries.
- The complete 34-test native GPU contract suite.
- Physical-GPU application workflow, admission, projection and telemetry checks
  from the normal deployment gate. Their CPU and simulated coverage still runs.

The native library and implementation hashes are unchanged. The new manifest
uses the fresh reports above and retains these five source/binary-verified
historical reports from validation/full-gpu-release-20261125:

- native/mining-gamma-gpu-1.json
- native/mining-kcgpu-gpu-1.json
- native/mining-kcore-gpu-gpu-1.json
- native/mining-libcugraph-gpu-1.json
- gpu-original.xml

The host dependency fingerprint was refreshed after the zlib update. Retaining
historical reports preserves existing GPU availability; it does not establish
fresh GPU validation for those five reports against the updated host dependency.
The evidence checks remain enabled, and the existing cuMBE correctness quarantine
is unchanged. The manifest records this exception in deferred_revalidation.

When physical GPU 1 has sufficient free memory, run from the development
checkout, with its existing matching library/build/runtime build:

```bash
export CUDA_VISIBLE_DEVICES=GPU-f9f2c156-0de4-a1f3-0c8a-a77ca24d10f7
export CUFILE_LOGFILE_PATH=/tmp/graphmine-iu-deferred-cufile.log
flock -w 120 /run/user/1002/graphmine-gpu-1.lock \
  python3 validation/iu-neo4j/resume-native.py
export GRAPHMINE_EVIDENCE_DEVICE=gpu GRAPHMINE_TEST_GPU=0
export GRAPHMINE_NATIVE_CPU_BUILD=/home/wajid/projects/graphDatabaseAgent/graphMine-runtime-20261125-full-gpu/library/build/runtime
export GRAPHMINE_NATIVE_LIBRARY="$GRAPHMINE_NATIVE_CPU_BUILD/libgraphmine_runtime.so"
export GRAPHMINE_IS_EVALUATION=true PYTHONPATH=python/graphmine
flock -w 120 /run/user/1002/graphmine-gpu-1.lock \
  /home/wajid/projects/graphDatabaseAgent/graphMine-repo/.venv-analytics/bin/python \
  -m pytest -q library/tests/test_native_original_gpu.py \
  --junitxml=validation/iu-neo4j/native-gpu1.xml
python3 tools/build_native_execution_evidence.py \
  --build library/build/runtime --source-root . \
  --reports validation/iu-neo4j/native-refresh \
  --junit validation/iu-neo4j/native-cpu.xml \
  --junit validation/iu-neo4j/native-gpu1.xml
```

Check that sources and the compiled library still match before reusing the
completed reports. Archive raw logs outside the checkout, review the manifest,
and rerun the original physical-GPU deployment commands recorded in
graphmine-data/environments/state/iu-neo4j-20261126/deferred-checks.json. Restore
those checks to the deployment configuration and promote the resulting evidence
through the normal testing workflow. Preserve the existing correctness quarantine.
