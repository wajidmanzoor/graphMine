# GraphMine performance — baseline-load-final

## 1. Summary

load requested 10 users; observed peak 10, with 9 users completing questions. 16 of 65 questions completed (75.38% error rate). Time to answer p50 248,262.32 ms, p95 316,443.59 ms. First recorded failure: client concurrency_limit at start_session (2026-11-19T03:44:09.832294+00:00).

Commit 27179494f778e2a2c8c9621e27d71ad8869b234a; dirty checkout: False. Started 2026-11-19T03:43:20.408397+00:00; finished including drain 2026-11-19T04:06:41.067108+00:00. An isolated application uses synthetic accounts and the real Yelp source, native runtime and shared model server. Provider and host metrics include other activity on this server; application traces identify this run.

Observed input projections (the test covers these snapshots, not every record in the source database):

| source_id | query | projection | vertices | edges | input_fingerprint |
| --- | --- | --- | --- | --- | --- |
| benchmark-yelp | MATCH (u:User)-[:WROTE]->(r:Review)-[:REVIEWS]->(b:Business) RETURN u AS source, b AS target, 'REVIEWED' AS type LIMIT 1000 | rows | 989 | 1000 | 52e718b73fd680a607915e644284f811fd790db36bdb5a21a801f13e1e57c449 |

| metric | value |
| --- | --- |
| users_requested | 10 |
| users_observed_peak | 10 |
| users_with_completed_questions | 9 |
| questions_attempted | 65 |
| questions_sent | 51 |
| questions_answered | 16 |
| question_error_percent | 75.38 |
| success_percent | 24.62 |
| busy_percent | 41.54 |
| wrong_operation_percent | 1.54 |
| routing_checks_available | 32 |
| answer_p50_ms | 248,262.32 |
| answer_p95_ms | 316,443.59 |
| answer_p99_ms | 316,443.59 |
| first_reply_p50_ms | 171,854.35 |
| first_reply_p95_ms | 191,268.89 |
| first_reply_p99_ms | 192,056.58 |
| result_view_p50_ms | 252.07 |
| result_view_p95_ms | 761.62 |
| result_view_p99_ms | 761.62 |
| model_queue_share_percent | 69.05 |
| model_calls | 243 |
| model_calls_per_question | 4.76 |
| routing_reasoning_share_percent | 71.63 |
| reasoning_calls_covered | 228 |
| vllm_preemptions | 0.00 |
| wake_count | 1 |
| wake_p95_ms | 1,767.00 |
| job_queue_p95_ms | 2,794.09 |
| job_queue_full | 0 |
| job_queue_timeouts | 0 |
| sqlite_slow_calls | 194 |
| sqlite_lock_p95_ms | 76.16 |
| sqlite_worst_lock_ms | 76.16 |
| exploration_saves | 0 |
| exploration_failures | 0 |
| peak_GPU 0 memory | 34,916.00 |
| peak_GPU 0 utilization | 100.00 |
| peak_GPU 1 memory | 13,136.00 |
| peak_GPU 1 utilization | 92.00 |
| peak_Host CPU | 91.61 |
| peak_Host RAM | 197,225.04 |
| peak_SQLite size | 97.78 |
| peak_agent RSS (process tree sum) | 1,422.05 |
| peak_vllm RSS (process tree sum) | 50,888.46 |

Coverage: {"answered_turns_expected": 46, "answered_turns_observed": 46, "db_lock_calls_measured": 1, "monitor_errors": 0, "reasoning_calls_measured": 242, "server_events": 11889, "system_samples": 701, "ttft_calls_measured": 228}. N/A means unmeasured, not zero. Percentiles use the nearest observed rank; no interpolated or estimated samples. Success requires the full journey including result views. Wrong-operation percentages use all attempts, with routing coverage shown separately.

## 2. User experience

| question | attempts | success_percent | busy_percent | wrong_operation_percent | routing_checked | first_reply_p50_ms | first_reply_p95_ms | first_reply_p99_ms | answer_p50_ms | answer_p95_ms | answer_p99_ms | results_p50_ms | results_p95_ms | results_p99_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| centrality | 8 | 25.00 | 25.00 | 0.00 | 2 | 133,792.51 | 163,218.81 | 163,218.81 | 222,187.23 | 272,997.55 | 272,997.55 | 565.02 | 761.62 | 761.62 |
| community-detection | 14 | 35.71 | 35.71 | 0.00 | 8 | 159,019.74 | 188,225.40 | 188,225.40 | 279,789.04 | 289,751.10 | 289,751.10 | 266.30 | 292.33 | 292.33 |
| concept | 7 | 28.57 | 71.43 | 0.00 | 2 | 132,062.62 | 153,649.79 | 153,649.79 | 132,062.84 | 153,650.08 | 153,650.08 | N/A | N/A | N/A |
| densest-subgraph | 13 | 53.85 | 46.15 | 7.69 | 7 | 175,286.90 | 181,782.66 | 181,782.66 | 271,436.76 | 316,443.59 | 316,443.59 | 234.34 | 251.38 | 251.38 |
| maximal-biclique-counting | 8 | 0.00 | 37.50 | 0.00 | 5 | 183,857.98 | 191,268.89 | 191,268.89 | N/A | N/A | N/A | N/A | N/A | N/A |
| maximal-bicliques | 15 | 0.00 | 40.00 | 0.00 | 8 | 172,409.21 | 192,056.58 | 192,056.58 | N/A | N/A | N/A | N/A | N/A | N/A |

All durations are milliseconds. First reply includes a choice or clarification; final answer waits for the final workflow answer. Documentation answers have no result view. For collection results the journey visits up to three available items; scalar results may have none.

## 3. Where the time goes

| question | component | milliseconds |
| --- | --- | --- |
| centrality | calculation | 699.21 |
| centrality | job queue | 2,185.89 |
| centrality | model queue | 170,022.10 |
| centrality | model: analyst | 1,289.69 |
| centrality | model: candidates | 11,123.93 |
| centrality | model: clarify | 4,281.54 |
| centrality | model: family | 7,412.45 |
| centrality | model: problem | 17,924.10 |
| centrality | model: route | 18,947.46 |
| centrality | other / overlap residual | 14,543.81 |
| centrality | result view build | 426.70 |
| community-detection | calculation | 999.24 |
| community-detection | job queue | 2,243.06 |
| community-detection | model queue | 176,430.88 |
| community-detection | model: analyst | 1,607.94 |
| community-detection | model: candidates | 11,115.31 |
| community-detection | model: clarify | 9,820.10 |
| community-detection | model: family | 8,473.02 |
| community-detection | model: problem | 18,223.28 |
| community-detection | model: route | 19,084.39 |
| community-detection | other / overlap residual | 15,011.64 |
| community-detection | result view build | 416.41 |
| concept | calculation | 0.00 |
| concept | job queue | 0.00 |
| concept | model queue | 104,446.09 |
| concept | model: analyst | 1,930.84 |
| concept | model: candidates | 0.00 |
| concept | model: clarify | 0.00 |
| concept | model: family | 8,525.01 |
| concept | model: problem | 13,581.62 |
| concept | model: route | 12,631.52 |
| concept | other / overlap residual | 1,741.40 |
| concept | result view build | 0.00 |
| densest-subgraph | calculation | 686.25 |
| densest-subgraph | job queue | 2,196.04 |
| densest-subgraph | model queue | 178,165.29 |
| densest-subgraph | model: analyst | 1,193.26 |
| densest-subgraph | model: candidates | 7,941.82 |
| densest-subgraph | model: clarify | 8,339.72 |
| densest-subgraph | model: family | 11,124.31 |
| densest-subgraph | model: problem | 15,862.16 |
| densest-subgraph | model: route | 17,668.03 |
| densest-subgraph | other / overlap residual | 12,603.83 |
| densest-subgraph | result view build | 134.21 |

[Average answered journey time by component (ms) — interactive chart](report.html#chart-0)

Joined by user, turn and workflow IDs for successful journeys. The span runs from question sent through opening results. Model time excludes model queue wait. Native attempts reuse existing runtime measurements; retries/fallbacks are included. Other is the measured span minus recorded components, including polling and wake time. Overlap can make the residual negative; it is retained. Missing event coverage can increase the residual.

## 4. Model

| stage | calls | calls_per_question | duration_ms | ttft_ms | prompt_tokens | completion_tokens | reasoning_tokens | reasoning_calls_covered | reasoning_share_percent | completion_tokens_per_second | validation_failures | retries |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| analyst | 14 | 0.27 | 1,630.97 | N/A | 312.14 | 38.86 | 0.00 | 14 | 0.00 | 23.54 | 0 | 0 |
| candidates | 30 | 0.59 | 10,709.46 | 832.58 | 528.27 | 327.93 | 0.00 | 30 | 0.00 | 31.90 | 0 | 0 |
| clarify | 81 | 1.59 | 8,009.56 | 587.51 | 506.56 | 202.38 | 185.15 | 81 | 91.48 | 25.67 | 0 | 0 |
| family | 40 | 0.78 | 10,735.92 | 1,109.40 | 1,407.53 | 261.82 | 218.07 | 40 | 83.29 | 25.04 | 0 | 0 |
| problem | 40 | 0.78 | 15,340.08 | 978.84 | 816.25 | 381.62 | 280.90 | 40 | 73.61 | 25.17 | 0 | 0 |
| route | 38 | 0.75 | 17,445.60 | 2,493.11 | 4,523.97 | 412.38 | 356.65 | 37 | 86.49 | 23.22 | 1 | 0 |

[vLLM running and waiting requests — interactive chart](report.html#chart-1)

[vLLM KV cache (%) — interactive chart](report.html#chart-2)

[vLLM observed token rates (/s) — interactive chart](report.html#chart-3)

Per-call throughput is reported completion tokens divided by transport time; it includes prefill and network time. TTFT is measured only for streaming calls, to the first content or reasoning delta. Reasoning counts are included only when returned by the provider. Histogram deltas are provider observations, without estimated quantiles. Counter resets have unknown increments.

| ts | event | duration_ms | trigger | request_id | turn_id |
| --- | --- | --- | --- | --- | --- |
| 2026-11-19T03:43:30.181717+00:00 | llm_wake | 1,767.00 | request | bb23c898-a3cc-4026-aa0c-dadb671a0f22 | ffe02d3b-a86e-4d1b-9aca-adbac5abb5ba |
| 2026-11-19T04:06:42.565254+00:00 | llm_sleep | 1,340.22 | admin | 16463996-9368-4085-9ff2-459a3037f949 | N/A |

| metric | labels | increase |
| --- | --- | --- |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "+Inf", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "0.3", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "0.5", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "0.8", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "1.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "1.5", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 8.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "10.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 229.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "120.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "15.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 297.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "1920.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "2.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 13.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "2.5", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 15.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "20.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 349.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "240.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "30.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "40.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "480.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "5.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 56.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "50.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "60.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "7680.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:e2e_request_latency_seconds_bucket | {"engine": "0", "le": "960.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:e2e_request_latency_seconds_count | {"engine": "0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:e2e_request_latency_seconds_created | {"engine": "0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:e2e_request_latency_seconds_sum | {"engine": "0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 3,436.25 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "+Inf", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.001", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.005", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.01", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.02", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.04", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.06", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.08", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.1", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.25", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 30.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.5", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 186.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "0.75", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 191.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "1.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 194.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "10.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 353.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "160.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "2.5", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 220.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "20.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "2560.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "40.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "5.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 282.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "640.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "7.5", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 333.00 |
| vllm:time_to_first_token_seconds_bucket | {"engine": "0", "le": "80.0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:time_to_first_token_seconds_count | {"engine": "0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 362.00 |
| vllm:time_to_first_token_seconds_created | {"engine": "0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 0.00 |
| vllm:time_to_first_token_seconds_sum | {"engine": "0", "model_name": "/data/labdata/wajid/graphmine-models/huggingface/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"} | 909.11 |

## 5. Calculations

| operation | device | attempts | outcomes | queue_p50_ms | queue_p95_ms | run_p50_ms | run_p95_ms | peak_gpu_mb |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| community-detection | cpu | 3 | {"error": 3} | 2,412.45 | 2,620.53 | 1,225.49 | 1,365.66 | 0.00 |
| community-detection | gpu | 5 | {"completed": 5} | 2,401.74 | 2,502.50 | 1,065.61 | 1,125.33 | 494.00 |
| degree-centrality | cpu | 2 | {"completed": 2} | 2,099.87 | 2,271.91 | 597.67 | 800.74 | N/A |
| densest-subgraph | cpu | 6 | {"completed": 6} | 2,520.80 | 3,055.10 | 797.81 | 833.61 | 0.00 |
| maximal-biclique-counting | cpu | 5 | {"error": 5} | 2,522.08 | 2,649.87 | 776.33 | 843.50 | 0.00 |
| maximal-bicliques | cpu | 8 | {"error": 8} | 2,413.86 | 2,794.09 | 697.63 | 811.93 | 0.00 |

Queue-full events: 0; queue-timeout events: 0. Queue timing spans account and device admission. A multi-operation workflow's shared queue wait is shown for each operation it contains, not added across operations.

## 6. System

[GPU and host utilization (%) — interactive chart](report.html#chart-4)

[GPU memory, host RAM, process RSS and SQLite size (MiB) — interactive chart](report.html#chart-5)

RSS sums can count shared pages more than once. SQLite size includes WAL and SHM files. Host RAM uses MemTotal minus MemAvailable. Only SQLite calls above 50 ms are logged; lock statistics describe measured slow BEGIN IMMEDIATE/EXCLUSIVE and application-lock waits. SQLite does not expose the busy-handler portion of arbitrary statements; those lock waits are N/A.

| ts | operation | duration_ms | lock_wait_ms | request_id |
| --- | --- | --- | --- | --- |
| 2026-11-19T03:58:23.437389+00:00 | BEGIN | 76.16 | 76.16 | 8c2a1905-a281-4b05-9f18-387ed7f59a99 |
| 2026-11-19T03:43:27.708547+00:00 | PRAGMA | 52.03 | N/A | cc18f777-17b8-4e80-aeb4-660b0ba09e5d |
| 2026-11-19T03:43:30.662381+00:00 | SELECT | 113.52 | N/A | 0bc301c2-5bde-4379-916c-236de83b2de3 |
| 2026-11-19T03:43:59.423742+00:00 | PRAGMA | 150.75 | N/A | ea67c6ab-1470-4b94-baba-4b3e087f2af9 |
| 2026-11-19T03:44:03.787979+00:00 | SELECT | 68.01 | N/A | bb23c898-a3cc-4026-aa0c-dadb671a0f22 |
| 2026-11-19T03:44:09.783615+00:00 | DELETE | 53.31 | N/A | 870ea7fe-315e-44d3-9dfa-2a70a0410c3b |
| 2026-11-19T03:44:16.061525+00:00 | SELECT | 74.21 | N/A | c69d142e-ed64-4ee1-bf1f-050d59895520 |
| 2026-11-19T03:45:23.059424+00:00 | PRAGMA | 50.85 | N/A | 0c234b69-50fe-412e-ae70-ad37cf9182ef |
| 2026-11-19T03:45:23.059547+00:00 | PRAGMA | 57.11 | N/A | 726a424d-45fc-4f87-acf0-fba119940f9f |
| 2026-11-19T03:46:14.623497+00:00 | SELECT | 208.36 | N/A | d3029f88-05e7-4064-a4cc-f07383460319 |
| 2026-11-19T03:46:15.234218+00:00 | PRAGMA | 62.96 | N/A | ddf31d23-e109-40a3-ba89-7b3e215b1415 |
| 2026-11-19T03:46:30.972152+00:00 | PRAGMA | 76.33 | N/A | b67b508f-e460-4a58-a54b-f7dcd8fd687d |
| 2026-11-19T03:46:31.039842+00:00 | PRAGMA | 53.35 | N/A | 030eddad-7798-4dff-9468-622868f4d9c8 |
| 2026-11-19T03:46:38.779273+00:00 | PRAGMA | 230.79 | N/A | 303b33bf-08f4-4600-84b1-eff2a6ed7549 |
| 2026-11-19T03:46:38.788935+00:00 | SELECT | 235.27 | N/A | a9f9d69c-7818-4825-9959-72088e18d890 |
| 2026-11-19T03:47:36.927388+00:00 | PRAGMA | 82.31 | N/A | f06255dc-ea89-4c6f-a34a-fc0ecad41e05 |
| 2026-11-19T03:47:52.546472+00:00 | SELECT | 52.11 | N/A | 67aec277-7d23-407a-8922-90833c753f3e |
| 2026-11-19T03:47:52.546848+00:00 | SELECT | 52.63 | N/A | bfeac68d-df8e-45e2-859c-609dea0b0845 |
| 2026-11-19T03:47:56.446269+00:00 | PRAGMA | 242.70 | N/A | 0086a9a2-eb18-488f-981c-ff4dc0b58d9b |
| 2026-11-19T03:47:57.666451+00:00 | PRAGMA | 60.42 | N/A | 2e88340c-0e79-47d0-a41c-aa941568ed95 |

No observations.

## 7. Errors

Client/journey failures and server observations are counted separately. Recovered server errors and an HTTP error may describe the same incident; these counts must not be summed into a user error rate.

| source | code | step | count |
| --- | --- | --- | --- |
| client | busy | query | 1 |
| client | concurrency_limit | plan | 13 |
| client | concurrency_limit | start_session | 13 |
| client | planner_unavailable | plan | 1 |
| journey | clarification_loop | clarify | 5 |
| journey | resource_limit | calculation | 16 |
| server | HTTPStatusError | model_call | 1 |
| server | busy | /api/database-sources/{source_id}/queries | 1 |
| server | concurrency_limit | <unmatched> | 26 |
| server | planner_unavailable | /api/sessions/{session_id}/analytics/plan | 1 |
| server | planner_unavailable | turn | 1 |
| server | resource_limit | job_run | 16 |

client / busy / query — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:58:23.353553+00:00 | 8c2a1905-a281-4b05-9f18-387ed7f59a99 | Database reads are busy. Retry shortly. |

client / concurrency_limit / plan — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:47:02.838479+00:00 | 258b4a5b-9808-49bd-ae43-93a4a2f29fa0 | Your request or the server is already busy. Please wait for current work to finish. |
| 2026-11-19T03:48:24.123906+00:00 | 32446360-3319-46ac-9d86-5293a382e814 | Your request or the server is already busy. Please wait for current work to finish. |
| 2026-11-19T03:49:04.344427+00:00 | 5bd084f8-d511-4a90-bd7c-d6be46d2a563 | Your request or the server is already busy. Please wait for current work to finish. |
| 2026-11-19T03:49:55.489855+00:00 | 1f8ca534-9895-4cc5-9436-22118dde9002 | Your request or the server is already busy. Please wait for current work to finish. |
| 2026-11-19T03:51:14.604006+00:00 | e15c1e5e-56da-4ebb-a4ae-965f962b3079 | Your request or the server is already busy. Please wait for current work to finish. |

client / concurrency_limit / start_session — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:44:09.832294+00:00 | 11b089d2-2fae-4bd4-9719-3fce8187f59f | Your request or the server is already busy. Please wait for current work to finish. |
| 2026-11-19T03:44:16.107319+00:00 | 1928016a-870c-48df-b292-133bfdeb8749 | Your request or the server is already busy. Please wait for current work to finish. |
| 2026-11-19T03:44:38.415802+00:00 | 6448d9ef-1a90-4ae9-8987-b5138d44388b | Your request or the server is already busy. Please wait for current work to finish. |
| 2026-11-19T03:45:04.949491+00:00 | ffb006f4-6e03-455b-8255-38fa32466b36 | Your request or the server is already busy. Please wait for current work to finish. |
| 2026-11-19T03:45:23.092605+00:00 | 262ffdcb-cf87-4aa3-9f47-bfaca7490a42 | Your request or the server is already busy. Please wait for current work to finish. |

client / planner_unavailable / plan — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:55:12.797933+00:00 | df0ef513-f72e-4d93-b50a-204ea730d780 | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |

journey / clarification_loop / clarify — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:49:08.036940+00:00 | 03f8aaba-2469-4485-8657-10fe52a35f15 | The question did not reach an answer or runnable plan after six follow-ups |
| 2026-11-19T03:50:04.739143+00:00 | 68edab1a-c982-4752-b05a-de0f2dc57df7 | The question did not reach an answer or runnable plan after six follow-ups |
| 2026-11-19T03:50:06.780560+00:00 | 5a42513f-110f-4d3a-adef-9569b61e2c25 | The question did not reach an answer or runnable plan after six follow-ups |
| 2026-11-19T04:05:20.619679+00:00 | 8df6d378-4551-4772-93c9-ec5453182471 | The question did not reach an answer or runnable plan after six follow-ups |
| 2026-11-19T04:05:38.295311+00:00 | 5ed7c7f4-3550-4e92-be8b-93c3c564bba9 | The question did not reach an answer or runnable plan after six follow-ups |

journey / resource_limit / calculation — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:47:36.532557+00:00 | 54479c58-038e-4795-996e-8595139f12e4 | Native candidate budget exceeded |
| 2026-11-19T03:48:39.281261+00:00 | 215944a7-29cf-45f1-8ce2-1aba8cdb3edc | Native candidate budget exceeded |
| 2026-11-19T03:52:27.660148+00:00 | 24fb14ef-a859-401e-9aa5-f8e9e70c9af7 | Native candidate budget exceeded |
| 2026-11-19T03:54:12.864719+00:00 | 0b0d3a90-8d3c-4205-aae1-7e599834da84 | Native candidate budget exceeded |
| 2026-11-19T03:55:40.319821+00:00 | 4ee770ac-1db0-4f7a-8bfd-ea393577af1f | Native candidate budget exceeded |

server / HTTPStatusError / model_call — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:57:35.749806+00:00 | df0ef513-f72e-4d93-b50a-204ea730d780 | Client error '400 Bad Request' for url 'http://127.0.0.1:8001/v1/chat/completions' For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 |

server / busy / /api/database-sources/{source_id}/queries — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:58:23.732059+00:00 | 8c2a1905-a281-4b05-9f18-387ed7f59a99 | Database reads are busy. Retry shortly. |

server / concurrency_limit / <unmatched> — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:44:09.838082+00:00 | 11b089d2-2fae-4bd4-9719-3fce8187f59f | Your request or the server is already busy. Please wait for current work to finish. |
| 2026-11-19T03:44:16.118609+00:00 | 1928016a-870c-48df-b292-133bfdeb8749 | Your request or the server is already busy. Please wait for current work to finish. |
| 2026-11-19T03:44:38.425110+00:00 | 6448d9ef-1a90-4ae9-8987-b5138d44388b | Your request or the server is already busy. Please wait for current work to finish. |
| 2026-11-19T03:45:04.959884+00:00 | ffb006f4-6e03-455b-8255-38fa32466b36 | Your request or the server is already busy. Please wait for current work to finish. |
| 2026-11-19T03:45:23.140088+00:00 | 262ffdcb-cf87-4aa3-9f47-bfaca7490a42 | Your request or the server is already busy. Please wait for current work to finish. |

server / planner_unavailable / /api/sessions/{session_id}/analytics/plan — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:57:35.770801+00:00 | df0ef513-f72e-4d93-b50a-204ea730d780 | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |

server / planner_unavailable / turn — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:57:35.765889+00:00 | df0ef513-f72e-4d93-b50a-204ea730d780 | The question planner is unavailable right now. Please try again shortly, or use Expert mode. |

server / resource_limit / job_run — first five examples

| time | request_id | message |
| --- | --- | --- |
| 2026-11-19T03:47:35.578192+00:00 | 1dbfd9b2-d19f-4f73-a758-22fb728dff40 | resource_limit |
| 2026-11-19T03:48:38.792643+00:00 | f672ae8a-0120-47c6-8479-258cb3c74c95 | resource_limit |
| 2026-11-19T03:52:26.611439+00:00 | 58d9409a-ee95-4a37-a0bc-d80ceacdc652 | resource_limit |
| 2026-11-19T03:54:11.876231+00:00 | 49b1069f-67be-407b-a6a1-377881197b15 | resource_limit |
| 2026-11-19T03:55:39.446231+00:00 | ee60050f-7977-4541-8c42-00fbe6e128c7 | resource_limit |

## 8. Stress only

Not a stress run. No breaking-point claim is made from this test.

## 9. Soak only

Not a soak run. Memory-growth and latency-drift slopes are not inferred.

## 10. Flags

| flag | measured_evidence |
| --- | --- |
| model concurrency is the bottleneck | {"percent": 69.0478793454686} |
| thinking on routing stages is costing time | {"calls_covered": 228, "percent": 71.62598360777663} |
| raise --max-num-seqs | {"kv_cache_percent": 9.411764705882353, "waiting": 8.0} |
| queue timeout too short or capacity too low | {"concurrency_limit_errors": 26} |

Flags are threshold-based investigation prompts, not proof of causality. Unavailable measurements cannot trigger a flag. Review coverage before treating absence of a flag as a pass.

## 11. Compare mode

Baseline: baseline-benchmark-final. All headline numbers are compared. Green means lower latency/error/cost or higher success; red means the reverse. Exposure counts are neutral. Change from a zero baseline is undefined (N/A). Different test shapes are not controlled experiments.

| metric | baseline | current | change_percent | assessment |
| --- | --- | --- | --- | --- |
| answer_p50_ms | 75,917.86 | 248,262.32 | 227.01 | regressed |
| answer_p95_ms | 82,975.64 | 316,443.59 | 281.37 | regressed |
| answer_p99_ms | 82,975.64 | 316,443.59 | 281.37 | regressed |
| busy_percent | 0.00 | 41.54 | N/A | regressed |
| exploration_failures | 0 | 0 | N/A | unchanged |
| exploration_saves | 0 | 0 | N/A | unchanged |
| first_reply_p50_ms | 43,426.52 | 171,854.35 | 295.74 | regressed |
| first_reply_p95_ms | 54,000.87 | 191,268.89 | 254.20 | regressed |
| first_reply_p99_ms | 54,928.67 | 192,056.58 | 249.65 | regressed |
| job_queue_full | 0 | 0 | N/A | unchanged |
| job_queue_p95_ms | 2,594.92 | 2,794.09 | 7.68 | regressed |
| job_queue_timeouts | 0 | 0 | N/A | unchanged |
| model_calls | 150 | 243 | 62.00 | regressed |
| model_calls_per_question | 5.00 | 4.76 | -4.71 | improved |
| model_queue_share_percent | 0.05 | 69.05 | 148,997.96 | regressed |
| peak_GPU 0 memory | 34,708.00 | 34,916.00 | 0.60 | regressed |
| peak_GPU 0 utilization | 100.00 | 100.00 | 0.00 | unchanged |
| peak_GPU 1 memory | 8,482.00 | 13,136.00 | 54.87 | regressed |
| peak_GPU 1 utilization | 92.00 | 92.00 | 0.00 | unchanged |
| peak_Host CPU | 94.37 | 91.61 | -2.93 | improved |
| peak_Host RAM | 193,882.00 | 197,225.04 | 1.72 | regressed |
| peak_SQLite size | 46.48 | 97.78 | 110.38 | regressed |
| peak_agent RSS (process tree sum) | 1,176.62 | 1,422.05 | 20.86 | regressed |
| peak_vllm RSS (process tree sum) | 50,305.47 | 50,888.46 | 1.16 | regressed |
| question_error_percent | 50.00 | 75.38 | 50.77 | regressed |
| questions_answered | 15 | 16 | 6.67 | improved |
| questions_attempted | 30 | 65 | 116.67 | neutral |
| questions_sent | 30 | 51 | 70.00 | neutral |
| reasoning_calls_covered | 135 | 228 | 68.89 | neutral |
| result_view_p50_ms | 228.08 | 252.07 | 10.52 | regressed |
| result_view_p95_ms | 622.82 | 761.62 | 22.29 | regressed |
| result_view_p99_ms | 622.82 | 761.62 | 22.29 | regressed |
| routing_checks_available | 25 | 32 | 28.00 | neutral |
| routing_reasoning_share_percent | 68.31 | 71.63 | 4.85 | regressed |
| sqlite_lock_p95_ms | N/A | 76.16 | N/A | not comparable |
| sqlite_slow_calls | 3 | 194 | 6,366.67 | regressed |
| sqlite_worst_lock_ms | N/A | 76.16 | N/A | not comparable |
| success_percent | 50.00 | 24.62 | -50.77 | regressed |
| users_observed_peak | 1 | 10 | 900.00 | neutral |
| users_requested | 1 | 10 | 900.00 | neutral |
| users_with_completed_questions | 1 | 9 | 800.00 | improved |
| vllm_preemptions | 0.00 | 0.00 | N/A | unchanged |
| wake_count | 0 | 1 | N/A | neutral |
| wake_p95_ms | N/A | 1,767.00 | N/A | not comparable |
| wrong_operation_percent | 0.00 | 1.54 | N/A | regressed |
