# GraphMine performance — baseline-benchmark-final

## 1. Summary

benchmark requested 1 users; observed peak 1, with 1 users completing questions. 15 of 30 questions completed (50.00% error rate). Time to answer p50 75,917.86 ms, p95 82,975.64 ms. First recorded failure: server resource_limit at job_run (2026-11-19T03:11:04.163296+00:00).

Commit bf7efa88708b111b2d1dace7e47107232fea7dde; dirty checkout: False. Started 2026-11-19T03:09:18.719631+00:00; finished including drain 2026-11-19T03:38:25.056797+00:00. An isolated application uses synthetic accounts and the real Yelp source, native runtime and shared model server. Provider and host metrics include other activity on this server; application traces identify this run.

Observed input projections (the test covers these snapshots, not every record in the source database):

| source_id | query | projection | vertices | edges | input_fingerprint |
| --- | --- | --- | --- | --- | --- |
| benchmark-yelp | MATCH (u:User)-[:WROTE]->(r:Review)-[:REVIEWS]->(b:Business) RETURN u AS source, b AS target, 'REVIEWED' AS type LIMIT 1000 | rows | 989 | 1000 | 52e718b73fd680a607915e644284f811fd790db36bdb5a21a801f13e1e57c449 |

| metric | value |
| --- | --- |
| users_requested | 1 |
| users_observed_peak | 1 |
| users_with_completed_questions | 1 |
| questions_attempted | 30 |
| questions_sent | 30 |
| questions_answered | 15 |
| question_error_percent | 50.00 |
| success_percent | 50.00 |
| busy_percent | 0.00 |
| wrong_operation_percent | 0.00 |
| routing_checks_available | 25 |
| answer_p50_ms | 75,917.86 |
| answer_p95_ms | 82,975.64 |
| answer_p99_ms | 82,975.64 |
| first_reply_p50_ms | 43,426.52 |
| first_reply_p95_ms | 54,000.87 |
| first_reply_p99_ms | 54,928.67 |
| result_view_p50_ms | 228.08 |
| result_view_p95_ms | 622.82 |
| result_view_p99_ms | 622.82 |
| model_queue_share_percent | 0.05 |
| model_calls | 150 |
| model_calls_per_question | 5.00 |
| routing_reasoning_share_percent | 68.31 |
| reasoning_calls_covered | 135 |
| vllm_preemptions | 0.00 |
| wake_count | 0 |
| wake_p95_ms | N/A |
| job_queue_p95_ms | 2,594.92 |
| job_queue_full | 0 |
| job_queue_timeouts | 0 |
| sqlite_slow_calls | 3 |
| sqlite_lock_p95_ms | N/A |
| sqlite_worst_lock_ms | N/A |
| exploration_saves | 0 |
| exploration_failures | 0 |
| peak_GPU 0 memory | 34,708.00 |
| peak_GPU 0 utilization | 100.00 |
| peak_GPU 1 memory | 8,482.00 |
| peak_GPU 1 utilization | 92.00 |
| peak_Host CPU | 94.37 |
| peak_Host RAM | 193,882.00 |
| peak_SQLite size | 46.48 |
| peak_agent RSS (process tree sum) | 1,176.62 |
| peak_vllm RSS (process tree sum) | 50,305.47 |

Coverage: {"answered_turns_expected": 41, "answered_turns_observed": 41, "db_lock_calls_measured": 0, "monitor_errors": 0, "reasoning_calls_measured": 145, "server_events": 3282, "system_samples": 874, "ttft_calls_measured": 135}. N/A means unmeasured, not zero. Percentiles use the nearest observed rank; no interpolated or estimated samples. Success requires the full journey including result views. Wrong-operation percentages use all attempts, with routing coverage shown separately.

## 2. User experience

| question | attempts | success_percent | busy_percent | wrong_operation_percent | routing_checked | first_reply_p50_ms | first_reply_p95_ms | first_reply_p99_ms | answer_p50_ms | answer_p95_ms | answer_p99_ms | results_p50_ms | results_p95_ms | results_p99_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| centrality | 5 | 100.00 | 0.00 | 0.00 | 5 | 52,951.12 | 54,000.87 | 54,000.87 | 78,818.69 | 79,050.78 | 79,050.78 | 515.90 | 622.82 | 622.82 |
| community-detection | 5 | 0.00 | 0.00 | 0.00 | 5 | 43,468.26 | 54,928.67 | 54,928.67 | N/A | N/A | N/A | N/A | N/A | N/A |
| concept | 5 | 100.00 | 0.00 | 0.00 | 5 | 30,035.69 | 38,226.45 | 38,226.45 | 30,036.00 | 38,226.68 | 38,226.68 | N/A | N/A | N/A |
| densest-subgraph | 5 | 100.00 | 0.00 | 0.00 | 5 | 44,827.20 | 52,211.71 | 52,211.71 | 75,917.86 | 82,975.64 | 82,975.64 | 216.29 | 228.08 | 228.08 |
| maximal-biclique-counting | 5 | 0.00 | 0.00 | 0.00 | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| maximal-bicliques | 5 | 0.00 | 0.00 | 0.00 | 5 | 37,498.18 | 39,529.28 | 39,529.28 | N/A | N/A | N/A | N/A | N/A | N/A |

All durations are milliseconds. First reply includes a choice or clarification; final answer waits for the final workflow answer. Documentation answers have no result view. For collection results the journey visits up to three available items; scalar results may have none.

## 3. Where the time goes

| question | component | milliseconds |
| --- | --- | --- |
| centrality | calculation | 701.84 |
| centrality | job queue | 2,210.90 |
| centrality | model queue | 33.37 |
| centrality | model: analyst | 1,166.77 |
| centrality | model: candidates | 8,006.87 |
| centrality | model: clarify | 7,187.96 |
| centrality | model: family | 8,748.97 |
| centrality | model: problem | 17,542.80 |
| centrality | model: route | 18,353.57 |
| centrality | other / overlap residual | 15,267.88 |
| centrality | result view build | 232.97 |
| concept | calculation | 0.00 |
| concept | job queue | 0.00 |
| concept | model queue | 16.12 |
| concept | model: analyst | 0.00 |
| concept | model: candidates | 0.00 |
| concept | model: clarify | 0.00 |
| concept | model: family | 9,773.54 |
| concept | model: problem | 10,702.42 |
| concept | model: route | 8,917.22 |
| concept | other / overlap residual | 2,257.81 |
| concept | result view build | 0.00 |
| densest-subgraph | calculation | 715.53 |
| densest-subgraph | job queue | 2,417.04 |
| densest-subgraph | model queue | 37.61 |
| densest-subgraph | model: analyst | 1,160.70 |
| densest-subgraph | model: candidates | 8,367.27 |
| densest-subgraph | model: clarify | 12,612.04 |
| densest-subgraph | model: family | 9,672.96 |
| densest-subgraph | model: problem | 16,297.41 |
| densest-subgraph | model: route | 13,041.33 |
| densest-subgraph | other / overlap residual | 13,768.20 |
| densest-subgraph | result view build | 117.29 |

[Average answered journey time by component (ms) — interactive chart](report.html#chart-0)

Joined by user, turn and workflow IDs for successful journeys. The span runs from question sent through opening results. Model time excludes model queue wait. Native attempts reuse existing runtime measurements; retries/fallbacks are included. Other is the measured span minus recorded components, including polling and wake time. Overlap can make the residual negative; it is retained. Missing event coverage can increase the residual.

## 4. Model

| stage | calls | calls_per_question | duration_ms | ttft_ms | prompt_tokens | completion_tokens | reasoning_tokens | reasoning_calls_covered | reasoning_share_percent | completion_tokens_per_second | validation_failures | retries |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| analyst | 10 | 0.33 | 1,163.73 | N/A | 297.00 | 31.00 | 0.00 | 10 | 0.00 | 26.64 | 0 | 0 |
| candidates | 20 | 0.67 | 8,048.94 | 521.96 | 557.75 | 324.50 | 0.00 | 20 | 0.00 | 40.36 | 0 | 0 |
| clarify | 30 | 1.00 | 6,687.30 | 417.92 | 392.50 | 187.23 | 166.40 | 30 | 88.87 | 28.41 | 0 | 0 |
| family | 30 | 1.00 | 9,262.31 | 341.41 | 1,424.00 | 264.57 | 219.93 | 30 | 83.13 | 28.48 | 0 | 0 |
| problem | 30 | 1.00 | 13,419.03 | 201.02 | 842.33 | 393.27 | 284.27 | 30 | 72.28 | 29.35 | 0 | 0 |
| route | 30 | 1.00 | 11,447.50 | 1,505.84 | 4,888.96 | 358.92 | 310.56 | 25 | 86.53 | 26.48 | 5 | 0 |

[vLLM running and waiting requests — interactive chart](report.html#chart-1)

[vLLM KV cache (%) — interactive chart](report.html#chart-2)

[vLLM observed token rates (/s) — interactive chart](report.html#chart-3)

Per-call throughput is reported completion tokens divided by transport time; it includes prefill and network time. TTFT is measured only for streaming calls, to the first content or reasoning delta. Reasoning counts are included only when returned by the provider. Histogram deltas are provider observations, without estimated quantiles. Counter resets have unknown increments.

| ts | event | duration_ms | trigger | request_id | turn_id |
| --- | --- | --- | --- | --- | --- |
| 2026-11-19T03:38:26.588185+00:00 | llm_sleep | 1,328.98 | admin | 097a5119-5e8e-443b-bfeb-e5ba6565307c | N/A |

| metric | labels | increase |
| --- | --- | --- |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "+Inf", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "0.3", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "0.5", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "0.8", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "1.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "1.5", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 12.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "10.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 188.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "120.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "15.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 214.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "1920.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "2.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 12.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "2.5", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 12.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "20.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "240.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "30.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "40.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "480.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "5.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 55.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "50.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "60.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "7680.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "960.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:e2e_request_latency_seconds_count | {"engine": "0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:e2e_request_latency_seconds_created | {"engine": "0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:e2e_request_latency_seconds_sum | {"engine": "0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 1,938.30 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "+Inf", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.001", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.005", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.01", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.02", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.04", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.06", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.08", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 3.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.1", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 7.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.25", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 63.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.5", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 133.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.75", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 160.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "1.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 160.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "10.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 243.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "160.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "2.5", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 170.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "20.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "2560.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "40.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "5.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 217.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "640.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "7.5", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 241.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "80.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:time_to_first_token_seconds_count | {"engine": "0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 245.00 |
| vllm:time_to_first_token_seconds_created | {"engine": "0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_sum | {"engine": "0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 411.05 |

## 5. Calculations

| operation | device | attempts | outcomes | queue_p50_ms | queue_p95_ms | run_p50_ms | run_p95_ms | peak_gpu_mb |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| community-detection | cpu | 5 | {"error": 5} | 2,443.66 | 2,555.07 | 1,218.10 | 1,287.35 | 0.00 |
| degree-centrality | cpu | 5 | {"completed": 5} | 2,197.04 | 2,574.25 | 698.01 | 734.46 | N/A |
| densest-subgraph | cpu | 5 | {"completed": 5} | 2,430.46 | 2,594.92 | 720.79 | 737.30 | 0.00 |
| maximal-bicliques | cpu | 5 | {"error": 5} | 2,411.33 | 2,625.21 | 753.69 | 814.67 | 0.00 |

Queue-full events: 0; queue-timeout events: 0. Queue timing spans account and device admission. A multi-operation workflow's shared queue wait is shown for each operation it contains, not added across operations.

## 6. System

[GPU and host utilization (%) — interactive chart](report.html#chart-4)

[GPU memory, host RAM, process RSS and SQLite size (MiB) — interactive chart](report.html#chart-5)

RSS sums can count shared pages more than once. SQLite size includes WAL and SHM files. Host RAM uses MemTotal minus MemAvailable. Only SQLite calls above 50 ms are logged; lock statistics describe measured slow BEGIN IMMEDIATE/EXCLUSIVE and application-lock waits. SQLite does not expose the busy-handler portion of arbitrary statements; those lock waits are N/A.

| ts | operation | duration_ms | lock_wait_ms | request_id |
| --- | --- | --- | --- | --- |
| 2026-11-19T03:25:36.263058+00:00 | PRAGMA | 190.48 | N/A | 2a4c14e8-1c9a-4b92-9ea5-959f65292db3 |
| 2026-11-19T03:30:01.321456+00:00 | PRAGMA | 80.05 | N/A | 50ff5211-fa45-4677-8eb7-bdbe8b7787da |
| 2026-11-19T03:35:43.326738+00:00 | SELECT | 91.62 | N/A | beac4dc9-9623-4e80-86cc-d205350b3ee5 |

No observations.

## 7. Errors

Client/journey failures and server observations are counted separately. Recovered server errors and an HTTP error may describe the same incident; these counts must not be summed into a user error rate.

| source | code | step | count |
| --- | --- | --- | --- |
| client | planner_unavailable | plan | 5 |
| journey | resource_limit | calculation | 10 |
| server | HTTPStatusError | model_call | 5 |
| server | planner_unavailable | /api/sessions/{session_id}/analytics/plan | 5 |
| server | planner_unavailable | turn | 5 |
| server | resource_limit | job_run | 10 |

client / planner_unavailable / plan — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:11:04.856809+00:00 | 828ffd1f-ea23-436f-86fa-36b2d8b2582c | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |
| 2026-11-19T03:17:04.995525+00:00 | 88c231c2-d1f7-4e70-be40-1a29df357d5e | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |
| 2026-11-19T03:22:53.510243+00:00 | d8e475bf-0142-4f27-b649-8cdd838fc8d4 | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |
| 2026-11-19T03:28:34.753197+00:00 | 6f350d39-e322-461d-8c9e-7bc812e446e6 | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |
| 2026-11-19T03:34:17.053904+00:00 | 9dd5b55c-e468-489f-b640-d65c1c083c2c | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |

journey / resource_limit / calculation — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:11:04.855923+00:00 | 6d6d6683-a417-4406-a092-f30ec0cbb059 | Native candidate budget exceeded |
| 2026-11-19T03:12:47.009465+00:00 | 4c0c54b9-e459-4f91-bac9-88c290896058 | Native candidate budget exceeded |
| 2026-11-19T03:17:04.994692+00:00 | 8ce1a1a9-5bc2-44af-a85b-9315b73128a0 | Native candidate budget exceeded |
| 2026-11-19T03:18:36.136084+00:00 | b09f9fe4-0f1b-4b56-87bc-a53ca2f79ed3 | Native candidate budget exceeded |
| 2026-11-19T03:22:53.509670+00:00 | 4c7bb395-ee4a-4616-87f9-f393c4bc04aa | Native candidate budget exceeded |

server / HTTPStatusError / model_call — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:11:30.599715+00:00 | 828ffd1f-ea23-436f-86fa-36b2d8b2582c | Client error '400 Bad Request' for url 'http://127.0.0.1:8001/v1/chat/completions' For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 |
| 2026-11-19T03:17:29.332368+00:00 | 88c231c2-d1f7-4e70-be40-1a29df357d5e | Client error '400 Bad Request' for url 'http://127.0.0.1:8001/v1/chat/completions' For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 |
| 2026-11-19T03:23:17.908591+00:00 | d8e475bf-0142-4f27-b649-8cdd838fc8d4 | Client error '400 Bad Request' for url 'http://127.0.0.1:8001/v1/chat/completions' For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 |
| 2026-11-19T03:28:59.379272+00:00 | 6f350d39-e322-461d-8c9e-7bc812e446e6 | Client error '400 Bad Request' for url 'http://127.0.0.1:8001/v1/chat/completions' For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 |
| 2026-11-19T03:34:41.354004+00:00 | 9dd5b55c-e468-489f-b640-d65c1c083c2c | Client error '400 Bad Request' for url 'http://127.0.0.1:8001/v1/chat/completions' For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 |

server / planner_unavailable / /api/sessions/{session_id}/analytics/plan — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:11:30.624795+00:00 | 828ffd1f-ea23-436f-86fa-36b2d8b2582c | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |
| 2026-11-19T03:17:29.369921+00:00 | 88c231c2-d1f7-4e70-be40-1a29df357d5e | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |
| 2026-11-19T03:23:17.928131+00:00 | d8e475bf-0142-4f27-b649-8cdd838fc8d4 | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |
| 2026-11-19T03:28:59.398291+00:00 | 6f350d39-e322-461d-8c9e-7bc812e446e6 | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |
| 2026-11-19T03:34:41.374342+00:00 | 9dd5b55c-e468-489f-b640-d65c1c083c2c | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |

server / planner_unavailable / turn — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:11:30.618506+00:00 | 828ffd1f-ea23-436f-86fa-36b2d8b2582c | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |
| 2026-11-19T03:17:29.364694+00:00 | 88c231c2-d1f7-4e70-be40-1a29df357d5e | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |
| 2026-11-19T03:23:17.923304+00:00 | d8e475bf-0142-4f27-b649-8cdd838fc8d4 | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |
| 2026-11-19T03:28:59.393547+00:00 | 6f350d39-e322-461d-8c9e-7bc812e446e6 | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |
| 2026-11-19T03:34:41.369135+00:00 | 9dd5b55c-e468-489f-b640-d65c1c083c2c | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |

server / resource_limit / job_run — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:11:04.163296+00:00 | 9bea4325-892f-429e-b41b-a34428415d4e | resource_limit |
| 2026-11-19T03:12:46.632224+00:00 | f804ea33-4e48-467e-9612-4b0ae1162349 | resource_limit |
| 2026-11-19T03:17:04.026830+00:00 | a9429cb6-71d8-4b03-a442-f7c62fd17819 | resource_limit |
| 2026-11-19T03:18:35.256288+00:00 | c3e5b8f2-5ec1-4a23-a420-1756bb9d0970 | resource_limit |
| 2026-11-19T03:22:52.566197+00:00 | 3b9a096a-02df-4c99-a553-fa127fc9e718 | resource_limit |

## 8. Stress only

Not a stress run. No breaking-point claim is made from this test.

## 9. Soak only

Not a soak run. Memory-growth and latency-drift slopes are not inferred.

## 10. Flags

| flag | measured_evidence |
| --- | --- |
| thinking on routing stages is costing time | {"calls_covered": 135, "percent": 68.31312017640573} |
| raise --max-num-seqs | {"kv_cache_percent": 9.411764705882353, "waiting": 8.0} |

Flags are threshold-based investigation prompts, not proof of causality. Unavailable measurements cannot trigger a flag. Review coverage before treating absence of a flag as a pass.

## 11. Compare mode

No comparison selected. Run perf/report.py <run> --compare <baseline-run> to compare every headline number.
