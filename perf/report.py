"""Reports derived exclusively from recorded samples, with missing-data coverage."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import html
import json
import math
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from perf.common import ROOT, mean, percentile, read_jsonl, seconds, write_json


def ratio(numerator, denominator):
    return 100*numerator/denominator if denominator else None


def stats(values):
    return {"p50":percentile(values,50), "p95":percentile(values,95), "p99":percentile(values,99)}


def slope(points):
    points = [(t,v) for t,v in points if isinstance(v,(int,float)) and math.isfinite(v)]
    if len(points) < 2:
        return {"per_hour":None,"percent_per_hour":None,"doubles_in_24h":None,"samples":len(points)}
    origin, baseline = points[0]
    xs, ys = [(t-origin)/3600 for t,v in points], [v for t,v in points]
    xmean, ymean = mean(xs), mean(ys)
    denominator = sum((x-xmean)**2 for x in xs)
    change = sum((x-xmean)*(y-ymean) for x,y in zip(xs,ys))/denominator if denominator else None
    percent = 100*change/baseline if change is not None and baseline > 0 else None
    return {"per_hour":change, "percent_per_hour":percent, "doubles_in_24h":percent >= 100/24 if percent is not None else None,
            "first_value":baseline,"last_value":ys[-1],"samples":len(points)}


def counter_increase(rows, key):
    values = [r["vllm"][key] for r in rows if r.get("vllm") and r["vllm"].get(key) is not None]
    if len(values) < 2:
        return None
    # A reset interval has unknown increments. Report the observed increases,
    # and surface resets separately rather than inventing a negative rate.
    return sum(b-a for a,b in zip(values,values[1:]) if b >= a)


def histograms(system):
    observations = [r["vllm"].get("histograms",[]) for r in system if r.get("vllm")]
    if len(observations) < 2:
        return []
    def keyed(rows):
        return {(r["name"],json.dumps(r["labels"],sort_keys=True)):r for r in rows}
    first, last = keyed(observations[0]), keyed(observations[-1])
    result = []
    for key,row in sorted(last.items()):
        before = first.get(key,{}).get("value")
        after = row["value"]
        delta = after-before if before is not None and after is not None and after >= before else None
        result.append({"metric":row["name"],"labels":row["labels"],"increase":delta})
    return result


def analyze(run):
    run = Path(run)
    config = json.loads((run/"config.json").read_text())
    questions, steps = read_jsonl(run/"questions.jsonl"), read_jsonl(run/"steps.jsonl")
    events, system = read_jsonl(run/"events.jsonl"), read_jsonl(run/"system.jsonl")
    shape, run_events = read_jsonl(run/"shape.jsonl"), read_jsonl(run/"run-events.jsonl")
    by_event = defaultdict(list)
    for event in events:
        by_event[event["event"]].append(event)
    sent = [q for q in questions if q.get("question_sent_at")]
    answered = [q for q in questions if q.get("outcome") == "success" and q.get("time_to_answer_ms") is not None]
    failed = [q for q in questions if q.get("outcome") != "success"]
    answer_times = [q.get("time_to_answer_ms") for q in answered]
    reply_times = [q.get("first_reply_ms") for q in questions]
    view_times = [q["results_page_ms"][0] for q in questions if q.get("results_page_ms")]
    busy_codes = {"busy","concurrency_limit","queue_full","queue_time_limit","login_busy"}
    headline = {"users_requested":config.get("requested_users"),
        "users_observed_peak":max((r["users"] for r in shape),default=None),
        "users_with_completed_questions":len({q["user_id"] for q in answered}),
        "questions_attempted":len(questions), "questions_sent":len(sent), "questions_answered":len(answered),
        "question_error_percent":ratio(len(failed),len(questions)),
        "success_percent":ratio(len(answered),len(questions)),
        "busy_percent":ratio(sum(q.get("error_code") in busy_codes for q in questions),len(questions)),
        "wrong_operation_percent":ratio(sum(q.get("wrong_operation") is True for q in questions),len(questions)),
        "routing_checks_available":sum(q.get("wrong_operation") is not None for q in questions)}
    for name,values in (("answer",answer_times),("first_reply",reply_times),("result_view",view_times)):
        headline.update({name+"_"+p+"_ms":v for p,v in stats(values).items()})
    question_stats = []
    for name in sorted({q["question_id"] for q in questions}):
        rows = [q for q in questions if q["question_id"] == name]
        row = {"question":name,"attempts":len(rows),
            "success_percent":ratio(sum(q["outcome"] == "success" for q in rows),len(rows)),
            "busy_percent":ratio(sum(q.get("error_code") in busy_codes for q in rows),len(rows)),
            "wrong_operation_percent":ratio(sum(q.get("wrong_operation") is True for q in rows),len(rows)),
            "routing_checked":sum(q.get("wrong_operation") is not None for q in rows)}
        for label,values in (("first_reply",[q.get("first_reply_ms") for q in rows]),
                             ("answer",[q.get("time_to_answer_ms") for q in rows if q["outcome"] == "success"]),
                             ("results",[q["results_page_ms"][0] for q in rows if q.get("results_page_ms")])):
            row.update({label+"_"+p+"_ms":v for p,v in stats(values).items()})
        question_stats.append(row)
    breakdown, queue_wait, answered_total, matched_turns = [], 0, 0, set()
    for question in answered:
        turn_ids = set(question.get("turn_ids", []))
        workflow = question.get("workflow_id")
        selected = [e for e in events if (e.get("turn_id") in turn_ids or (workflow and e.get("workflow_id") == workflow))
                    and (not e.get("user_id") or e.get("user_id") == question["user_id"])]
        matched_turns.update(e.get("turn_id") for e in selected if e["event"] == "turn_end")
        if not selected:
            continue
        components = defaultdict(float)
        for event in selected:
            kind = event["event"]
            if kind == "model_queue":
                components["model queue"] += event.get("wait_ms") or 0
            elif kind == "model_call":
                components["model: "+event["stage"]] += event.get("duration_ms") or 0
            elif kind == "job_queue":
                components["job queue"] += event.get("wait_ms") or 0
            elif kind == "job_run":
                components["calculation"] += event.get("duration_ms") or 0
            elif kind == "result_view":
                components["result view build"] += event.get("duration_ms") or 0
        duration = (seconds(question["end"])-seconds(question["question_sent_at"]))*1000
        components["other / overlap residual"] = duration-sum(components.values())
        for component,value in components.items():
            breakdown.append({"question":question["question_id"],"instance":question["question_instance_id"],"component":component,"milliseconds":value})
        queue_wait += components["model queue"]
        answered_total += question["time_to_answer_ms"]
    headline["model_queue_share_percent"] = ratio(queue_wait,answered_total) if breakdown else None
    calls = by_event["model_call"]
    model_stats = []
    for stage in sorted({r.get("stage","unknown") for r in calls}):
        rows = [r for r in calls if r.get("stage") == stage]
        covered = [r for r in rows if r.get("reasoning_tokens") is not None and r.get("completion_tokens") is not None]
        throughput = [1000*r["completion_tokens"]/r["duration_ms"] for r in rows if r.get("completion_tokens") is not None and r.get("duration_ms")]
        model_stats.append({"stage":stage,"calls":len(rows),"calls_per_question":len(rows)/len(sent) if sent else None,
            "duration_ms":mean([r.get("duration_ms") for r in rows]),"ttft_ms":mean([r.get("time_to_first_token_ms") for r in rows]),
            "prompt_tokens":mean([r.get("prompt_tokens") for r in rows]),"completion_tokens":mean([r.get("completion_tokens") for r in rows]),
            "reasoning_tokens":mean([r.get("reasoning_tokens") for r in rows]),"reasoning_calls_covered":len(covered),
            "reasoning_share_percent":ratio(sum(r["reasoning_tokens"] for r in covered),sum(r["completion_tokens"] for r in covered)),
            "completion_tokens_per_second":mean(throughput),"validation_failures":sum(bool(r.get("validation_failed")) for r in rows),
            "retries":sum(r.get("retries",0)>0 for r in rows)})
    routing = [r for r in calls if r.get("stage") in {"family","problem","route","clarify","candidates"}
               and r.get("reasoning_tokens") is not None and r.get("completion_tokens") is not None]
    headline.update(model_calls=len(calls),model_calls_per_question=len(calls)/len(sent) if sent else None,
        routing_reasoning_share_percent=ratio(sum(r["reasoning_tokens"] for r in routing),sum(r["completion_tokens"] for r in routing)),
        reasoning_calls_covered=len(routing),vllm_preemptions=counter_increase(system,"preemptions_total"),
        wake_count=len(by_event["llm_wake"]),wake_p95_ms=percentile([r.get("duration_ms") for r in by_event["llm_wake"]],95),
        job_queue_p95_ms=percentile([r.get("wait_ms") for r in by_event["job_queue"]],95),
        job_queue_full=sum(r.get("outcome") == "queue_full" for r in by_event["job_queue"]),
        job_queue_timeouts=sum(r.get("outcome") == "queue_timeout" for r in by_event["job_queue"]),
        sqlite_slow_calls=len(by_event["db"]),sqlite_lock_p95_ms=percentile([r.get("lock_wait_ms") for r in by_event["db"]],95),
        sqlite_worst_lock_ms=max((r["lock_wait_ms"] for r in by_event["db"] if r.get("lock_wait_ms") is not None),default=None),
        exploration_saves=len(by_event["exploration_save"]),exploration_failures=sum(r.get("outcome") != "saved" for r in by_event["exploration_save"]))
    calculations = []
    for operation,device in sorted({(r.get("operation") or "unknown",r.get("device") or "unknown") for r in by_event["job_run"]}):
        rows = [r for r in by_event["job_run"] if (r.get("operation") or "unknown",r.get("device") or "unknown") == (operation,device)]
        workflows = {r.get("workflow_id") for r in rows if r.get("workflow_id")}
        waits = [r.get("wait_ms") for r in by_event["job_queue"] if r.get("workflow_id") in workflows]
        calculations.append({"operation":operation,"device":device,"attempts":len(rows),
            "outcomes":dict(Counter(r.get("outcome") for r in rows)),"queue_p50_ms":percentile(waits,50),"queue_p95_ms":percentile(waits,95),
            "run_p50_ms":percentile([r.get("duration_ms") for r in rows],50),"run_p95_ms":percentile([r.get("duration_ms") for r in rows],95),
            "peak_gpu_mb":max((r["peak_gpu_mb"] for r in rows if r.get("peak_gpu_mb") is not None),default=None)})
    series = []
    def point(row,name,value,unit):
        if isinstance(value,(int,float)) and math.isfinite(value):
            series.append({"ts":row["ts"],"series":name,"value":value,"unit":unit})
    for row in system:
        for gpu in row.get("gpu") or []:
            name = "GPU "+str(int(gpu["index"]))
            point(row,name+" utilization",gpu.get("utilization_percent"),"percent")
            point(row,name+" memory",gpu.get("memory_used_mb"),"MiB")
        host = row.get("host") or {}
        point(row,"Host CPU",host.get("cpu_percent"),"percent")
        point(row,"Host RAM",host.get("ram_used_bytes",0)/1024**2 if host.get("ram_used_bytes") is not None else None,"MiB")
        point(row,"SQLite size",row.get("sqlite_bytes",0)/1024**2 if row.get("sqlite_bytes") is not None else None,"MiB")
        for name,process in (row.get("processes") or {}).items():
            value = process.get("tree_rss_bytes")
            point(row,name+" RSS (process tree sum)",value/1024**2 if value is not None else None,"MiB")
    for name in sorted({r["series"] for r in series}):
        headline["peak_"+name] = max(r["value"] for r in series if r["series"] == name)
    trends = {}
    if config["test"] == "soak":
        for name in sorted({r["series"] for r in series if r["unit"] == "MiB"}):
            trends[name] = slope([(seconds(r["ts"]),r["value"]) for r in series if r["series"] == name])
        buckets = defaultdict(list)
        for q in answered:
            buckets[int(seconds(q["question_sent_at"])//300)*300].append(q["time_to_answer_ms"])
        latency_points = [(t,percentile(values,95)) for t,values in sorted(buckets.items())]
        trends["p95 answer latency (ms, five-minute windows)"] = slope(latency_points)
        for t,value in latency_points:
            from datetime import datetime,timezone
            point({"ts":datetime.fromtimestamp(t,timezone.utc).isoformat()},"p95 answer latency",value,"ms")
    for name,value in trends.items():
        headline["slope_percent_per_hour_"+name] = value["percent_per_hour"]
    # Client errors represent failed user steps; server errors include recovered
    # provider/validation failures. Keep the two counts explicitly separate.
    error_rows = [{"source":"client", "code":r.get("error_code") or "unknown", "step":r["step"],
                   "time":r["start"],"request_id":r.get("request_id"),"message":r.get("message"),
                   "question_instance_id":r.get("question_instance_id")} for r in steps if r.get("outcome") == "error"]
    for q in failed:
        if not any(e.get("question_instance_id") == q.get("question_instance_id") and e["code"] == q.get("error_code") for e in error_rows):
            error_rows.append({"source":"journey","code":q.get("error_code") or "interrupted","step":q.get("error_step") or "question",
                               "time":q["end"],"request_id":None,"message":q.get("message")})
    error_rows.extend({"source":"server","code":r.get("error_code") or "unknown","step":r.get("where") or "unknown",
                       "time":r["ts"],"request_id":r.get("request_id"),"message":r.get("message")} for r in by_event["error"])
    errors = []
    for key in sorted({(r["source"],r["code"],r["step"]) for r in error_rows}):
        rows = sorted((r for r in error_rows if (r["source"],r["code"],r["step"]) == key),key=lambda r:r["time"])
        errors.append({"source":key[0],"code":key[1],"step":key[2],"count":len(rows),"examples":rows[:5]})
    flags = []
    def flag(condition,message,**evidence):
        if condition:
            flags.append({"message":message,**evidence})
    flag((headline["model_queue_share_percent"] or 0)>30,"model concurrency is the bottleneck",percent=headline["model_queue_share_percent"])
    flag((headline["routing_reasoning_share_percent"] or 0)>60,"thinking on routing stages is costing time",percent=headline["routing_reasoning_share_percent"],calls_covered=len(routing))
    waiting = [r["vllm"] for r in system if r.get("vllm") and (r["vllm"].get("waiting") or 0)>0 and r["vllm"].get("kv_cache_percent") is not None and r["vllm"]["kv_cache_percent"]<70]
    if waiting:
        sample = max(waiting,key=lambda r:r["waiting"])
        flag(True,"raise --max-num-seqs",waiting=sample["waiting"],kv_cache_percent=sample["kv_cache_percent"])
    flag((headline["vllm_preemptions"] or 0)>0,"KV cache too small for current concurrency",observed_preemptions=headline["vllm_preemptions"])
    concurrency = sum(e["count"] for e in errors if e["code"] == "concurrency_limit" and e["source"] != "server")
    if not concurrency:
        concurrency = sum(e["count"] for e in errors if e["code"] == "concurrency_limit" and e["source"] == "server")
    flag(concurrency>0,"queue timeout too short or capacity too low",concurrency_limit_errors=concurrency)
    flag((headline["job_queue_p95_ms"] or 0)>30000,"calculation slots are the bottleneck",p95_ms=headline["job_queue_p95_ms"])
    flag((headline["sqlite_lock_p95_ms"] or 0)>200,"database contention",p95_ms=headline["sqlite_lock_p95_ms"])
    flag((headline["result_view_p95_ms"] or 0)>2000 or headline["exploration_failures"]>0,"results payloads too large",result_p95_ms=headline["result_view_p95_ms"],save_failures=headline["exploration_failures"])
    flag((headline["wake_p95_ms"] or 0)>15000,"sleep level / idle timeout needs tuning",p95_ms=headline["wake_p95_ms"])
    for name,trend in trends.items():
        flag("latency" not in name and (trend["percent_per_hour"] or 0)>5,"possible leak",series=name,percent_per_hour=trend["percent_per_hour"])
    stress = []
    if config["test"] == "stress":
        for users in sorted({q.get("users") for q in questions if q.get("users") is not None}):
            rows = [q for q in questions if q.get("users") == users]
            stress.append({"users":users,"questions":len(rows),"p95_answer_ms":percentile([q.get("time_to_answer_ms") for q in rows if q["outcome"] == "success"],95),
                           "error_percent":ratio(sum(q["outcome"] != "success" for q in rows),len(rows))})
    coverage = {"server_events":len(events),"system_samples":len(system),
        "monitor_errors":sum(len(r.get("errors",[])) for r in system),"answered_turns_observed":len(matched_turns),
        "answered_turns_expected":len({t for q in answered for t in q.get("turn_ids",[])}),
        "ttft_calls_measured":sum(r.get("time_to_first_token_ms") is not None for r in calls),
        "reasoning_calls_measured":sum(r.get("reasoning_tokens") is not None for r in calls),
        "db_lock_calls_measured":sum(r.get("lock_wait_ms") is not None for r in by_event["db"])}
    return {"config":config,"headline":headline,"questions":question_stats,"breakdown":breakdown,"model":model_stats,
        "calculations":calculations,"series":series,"system":system,"histograms":histograms(system),
        "power_events":[e for e in events if e["event"] in {"llm_wake","llm_sleep"}],
        "saves":by_event["exploration_save"],"db":by_event["db"],"errors":errors,"trends":trends,
        "stress":stress,"breaking_points":[r for r in run_events if r.get("event") == "breaking_point"],
        "flags":flags,"coverage":coverage,
        "first_error":min(error_rows,key=lambda r:r["time"]) if error_rows else None}


SECTIONS = ["Summary", "User experience", "Where the time goes", "Model", "Calculations", "System", "Errors",
            "Stress only", "Soak only", "Flags", "Compare mode"]


def display(value):
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def table(rows, columns=None):
    if not rows:
        return "No observations.\n", "<p>No observations.</p>"
    columns = columns or list(rows[0])
    def cell(value):
        return display(value).replace("|", "\\|").replace("\n", " ")
    md = "| " + " | ".join(columns) + " |\n| " + " | ".join("---" for _ in columns) + " |\n"
    md += "".join("| " + " | ".join(cell(row.get(k)) for k in columns) + " |\n" for row in rows)
    markup = "<div class='table'><table><thead><tr>" + "".join("<th>"+html.escape(k)+"</th>" for k in columns) + "</tr></thead><tbody>"
    markup += "".join("<tr>"+"".join("<td>"+html.escape(display(row.get(k)))+"</td>" for k in columns)+"</tr>" for row in rows)
    return md, markup+"</tbody></table></div>"


def comparisons(current, previous):
    # Counts that describe exposure are neutral: a longer run is not an improvement.
    higher = {"success_percent", "users_with_completed_questions", "questions_answered"}
    neutral = {"users_requested", "users_observed_peak", "questions_attempted", "questions_sent", "routing_checks_available",
               "reasoning_calls_covered", "wake_count", "exploration_saves"}
    rows = []
    for key in sorted(set(current) | set(previous)):
        before, after = previous.get(key), current.get(key)
        numeric = all(isinstance(v, (int, float)) for v in (before, after))
        delta = 100*(after-before)/abs(before) if numeric and before else None
        verdict = "not comparable" if not numeric else "unchanged" if after == before else "neutral" if key in neutral else (
            "improved" if (after > before) == (key in higher) else "regressed")
        rows.append({"metric":key,"baseline":before,"current":after,"change_percent":delta,"assessment":verdict})
    return rows


def line_spec(values, title, *, y="value", color="series", x="ts", xtype="temporal"):
    return {"$schema":"https://vega.github.io/schema/vega-lite/v5.json", "title":title,
            "width":"container", "height":250, "data":{"values":values}, "mark":{"type":"line","point":False},
            "encoding":{"x":{"field":x,"type":xtype},"y":{"field":y,"type":"quantitative","scale":{"zero":False}},
                        "color":{"field":color,"type":"nominal"},"tooltip":[{"field":k} for k in (x,color,y)]}}


def render(data, previous=None):
    md, markup, charts = [], [], []
    def heading(index):
        title = f"{index}. {SECTIONS[index-1]}"
        md.append("## "+title+"\n")
        markup.append("<h2>"+html.escape(title)+"</h2>")
    def paragraph(value):
        md.append(value+"\n")
        markup.append("<p>"+html.escape(value)+"</p>")
    def rows(values, columns=None):
        a,b = table(values, columns)
        md.append(a); markup.append(b)
    def chart(spec):
        name = "chart-"+str(len(charts))
        charts.append((name,spec))
        markup.append(f"<div class='chart' id='{name}'></div>")
        md.append(f"[{spec['title']} — interactive chart](report.html#{name})\n")

    config, h = data["config"], data["headline"]
    title = "GraphMine performance — "+config.get("label", "run")
    if config.get("preflight"):
        title += " (PREFLIGHT ONLY; not a benchmark result)"
    md.append("# "+title+"\n"); markup.append("<h1>"+html.escape(title)+"</h1>")
    heading(1)
    first = data["first_error"]
    failure = f"First recorded failure: {first['source']} {first['code']} at {first['step']} ({first['time']})." if first else "No failures were recorded."
    paragraph(f"{config['test']} requested {display(h['users_requested'])} users; observed peak {display(h['users_observed_peak'])}, "
        f"with {h['users_with_completed_questions']} users completing questions. {h['questions_answered']} of {h['questions_attempted']} questions "
        f"completed ({display(h['question_error_percent'])}% error rate). Time to answer p50 {display(h['answer_p50_ms'])} ms, "
        f"p95 {display(h['answer_p95_ms'])} ms. {failure}")
    paragraph(f"Commit {config.get('git_commit','N/A')}; dirty checkout: {config.get('git_dirty','N/A')}. "
              f"Started {config.get('started_at','N/A')}; finished including drain {config.get('finished_at','N/A')}. "
              "An isolated application uses synthetic accounts and the real Yelp source, native runtime and shared model server. "
              "Provider and host metrics include other activity on this server; application traces identify this run.")
    for key in ("infrastructure_error","sleep_error","stop_error","cleanup_error","validation_error"):
        if config.get(key):
            paragraph(key+": "+str(config[key]))
    rows([{"metric":k,"value":v} for k,v in h.items()])
    paragraph("Coverage: "+display(data["coverage"])+". N/A means unmeasured, not zero. Percentiles use the nearest observed rank; no interpolated or estimated samples. Success requires the full journey including result views. Wrong-operation percentages use all attempts, with routing coverage shown separately.")
    heading(2)
    rows(data["questions"])
    paragraph("All durations are milliseconds. First reply includes a choice or clarification; final answer waits for the final workflow answer. Documentation answers have no result view. For collection results the journey visits up to three available items; scalar results may have none.")
    heading(3)
    grouped = defaultdict(dict)
    for row in data["breakdown"]:
        grouped[(row["question"],row["instance"])][row["component"]] = row["milliseconds"]
    components = sorted({r["component"] for r in data["breakdown"]})
    averages = []
    for question in sorted({key[0] for key in grouped}):
        instances = [v for (q,_),v in grouped.items() if q == question]
        for component in components:
            averages.append({"question":question,"component":component,"milliseconds":mean([v.get(component,0) for v in instances])})
    rows(averages)
    chart({"$schema":"https://vega.github.io/schema/vega-lite/v5.json", "title":"Average answered journey time by component (ms)",
        "width":"container", "height":320, "data":{"values":averages}, "mark":"bar", "encoding":{
            "y":{"field":"question","type":"nominal"},"x":{"field":"milliseconds","type":"quantitative","stack":"zero"},
            "color":{"field":"component","type":"nominal"},"tooltip":[{"field":k} for k in ("question","component","milliseconds")]}})
    paragraph("Joined by user, turn and workflow IDs for successful journeys. The span runs from question sent through opening results. Model time excludes model queue wait. Native attempts reuse existing runtime measurements; retries/fallbacks are included. Other is the measured span minus recorded components, including polling and wake time. Overlap can make the residual negative; it is retained. Missing event coverage can increase the residual.")
    heading(4)
    rows(data["model"])
    provider = []
    for row in data["system"]:
        for key in ("running","waiting","kv_cache_percent","prompt_tokens_per_second","generation_tokens_per_second"):
            value = (row.get("vllm") or {}).get(key)
            if value is not None:
                provider.append({"ts":row["ts"],"series":key,"value":value})
    for keys,title2 in (({"running","waiting"},"vLLM running and waiting requests"),({"kv_cache_percent"},"vLLM KV cache (%)"),
                        ({"prompt_tokens_per_second","generation_tokens_per_second"},"vLLM observed token rates (/s)")):
        chart(line_spec([r for r in provider if r["series"] in keys],title2))
    paragraph("Per-call throughput is reported completion tokens divided by transport time; it includes prefill and network time. TTFT is measured only for streaming calls, to the first content or reasoning delta. Reasoning counts are included only when returned by the provider. Histogram deltas are provider observations, without estimated quantiles. Counter resets have unknown increments.")
    rows(data["power_events"], ["ts","event","duration_ms","trigger","request_id","turn_id"])
    rows(data["histograms"])
    heading(5)
    rows(data["calculations"])
    paragraph(f"Queue-full events: {h['job_queue_full']}; queue-timeout events: {h['job_queue_timeouts']}. Queue timing spans account and device admission. A multi-operation workflow's shared queue wait is shown for each operation it contains, not added across operations.")
    heading(6)
    for unit,title2 in (("percent","GPU and host utilization (%)"),("MiB","GPU memory, host RAM, process RSS and SQLite size (MiB)")):
        chart(line_spec([r for r in data["series"] if r["unit"] == unit],title2))
    paragraph("RSS sums can count shared pages more than once. SQLite size includes WAL and SHM files. Host RAM uses MemTotal minus MemAvailable. Only SQLite calls above 50 ms are logged; lock statistics describe measured slow BEGIN IMMEDIATE/EXCLUSIVE and application-lock waits. SQLite does not expose the busy-handler portion of arbitrary statements; those lock waits are N/A.")
    rows(sorted(data["db"],key=lambda r:r.get("lock_wait_ms") or 0,reverse=True)[:20], ["ts","operation","duration_ms","lock_wait_ms","request_id"])
    rows(data["saves"], ["ts","payload_bytes","duration_ms","outcome","request_id"])
    heading(7)
    paragraph("Client/journey failures and server observations are counted separately. Recovered server errors and an HTTP error may describe the same incident; these counts must not be summed into a user error rate.")
    rows(data["errors"], ["source","code","step","count"])
    for error in data["errors"]:
        paragraph(f"{error['source']} / {error['code']} / {error['step']} — first five examples")
        rows(error["examples"], ["time","request_id","message"])
    heading(8)
    if config["test"] == "stress":
        rows(data["stress"])
        rows(data["breaking_points"])
        for field in ("p95_answer_ms","error_percent"):
            values = [{**r,"series":field} for r in data["stress"]]
            spec = line_spec(values,"Stress: users vs "+field,y=field,x="users",xtype="quantitative")
            breaks = data["breaking_points"]
            if breaks:
                spec = {"title":spec["title"],"width":"container","height":250,"layer":[
                    {k:v for k,v in spec.items() if k not in {"title","width","height","$schema"}},
                    {"data":{"values":breaks},"mark":{"type":"rule","color":"red"},"encoding":{"x":{"field":"users","type":"quantitative"}}}]}
            chart(spec)
    else:
        paragraph("Not a stress run. No breaking-point claim is made from this test.")
    heading(9)
    if config["test"] == "soak":
        rows([{"series":name,**trend} for name,trend in data["trends"].items()])
        for unit in ("MiB","ms"):
            values = [r for r in data["series"] if r["unit"] == unit]
            spec = line_spec(values,"Soak observations and linear trends ("+unit+")")
            base = {k:v for k,v in spec.items() if k not in {"title","width","height","$schema"}}
            regression = {**base,"transform":[{"regression":"value","on":"ts","groupby":["series"]}],
                          "mark":{"type":"line","strokeDash":[6,3]}}
            # Vega regression requires numeric x, so retain raw observation chart
            # and compute the fitted points from the measured OLS coefficients.
            fitted = []
            for name in {r["series"] for r in values}:
                selected = [r for r in values if r["series"] == name]
                result = slope([(seconds(r["ts"]),r["value"]) for r in selected])
                if result["per_hour"] is None:
                    continue
                origin = seconds(selected[0]["ts"])
                intercept = mean([r["value"] for r in selected])-result["per_hour"]*mean([(seconds(r["ts"])-origin)/3600 for r in selected])
                for row in (selected[0],selected[-1]):
                    fitted.append({**row,"value":intercept+result["per_hour"]*(seconds(row["ts"])-origin)/3600})
            regression.pop("transform")
            regression["data"] = {"values":fitted}
            chart({"title":spec["title"],"width":"container","height":250,"layer":[base,regression]})
        paragraph("Slopes use ordinary least squares on measured samples, relative to the first observed value. The 24-hour flag is a linear extrapolation test requested by the suite, not a measured 24-hour result. Latency uses p95 in five-minute windows.")
    else:
        paragraph("Not a soak run. Memory-growth and latency-drift slopes are not inferred.")
    heading(10)
    rows([{"flag":r["message"],"measured_evidence":{k:v for k,v in r.items() if k != "message"}} for r in data["flags"]])
    paragraph("Flags are threshold-based investigation prompts, not proof of causality. Unavailable measurements cannot trigger a flag. Review coverage before treating absence of a flag as a pass.")
    heading(11)
    if previous:
        paragraph("Baseline: "+previous["config"].get("label", "run")+". All headline numbers are compared. Green means lower latency/error/cost or higher success; red means the reverse. Exposure counts are neutral. Change from a zero baseline is undefined (N/A). Different test shapes are not controlled experiments.")
        rows(comparisons(h, previous["headline"]))
    else:
        paragraph("No comparison selected. Run perf/report.py <run> --compare <baseline-run> to compare every headline number.")
    scripts = []
    vendor = ROOT/"agent/graphmine_agent/static/vendor"
    for name in ("vega.min.js","vega-lite.min.js","vega-embed.min.js"):
        scripts.append("<script>"+(vendor/name).read_text().replace("</script", "<\\/script")+"</script>")
    for name,spec in charts:
        payload = json.dumps(spec,ensure_ascii=False,allow_nan=False).replace("<", "\\u003c")
        scripts.append(f"<script>vegaEmbed('#{name}', {payload}, {{actions: true}}).catch(e => document.getElementById('{name}').textContent=e.message);</script>")
    scripts.append("<script>document.querySelectorAll('td').forEach(c=>{if(c.textContent==='improved')c.className='good';if(c.textContent==='regressed')c.className='bad';});</script>")
    licenses = [p for p in vendor.glob("*LICENSE*") if "vega" in p.name.lower()]
    markup.append("<details><summary>Vendored chart licenses</summary><pre>"+html.escape("\n".join(p.read_text() for p in licenses))+"</pre></details>")
    style = "body{font:16px system-ui;margin:32px auto;max-width:1300px;padding:0 24px;color:#172b40;background:#fff}h1,h2{color:#123a59}h2{margin-top:40px}p{line-height:1.6}.table{overflow:auto}table{border-collapse:collapse;font-size:13px;width:100%}th,td{padding:9px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}th{background:#eef3f8;position:sticky;top:0}.chart{width:100%;margin:24px 0}.good{color:#17662a;background:#e8f7ec}.bad{color:#a51623;background:#fdecee}pre{white-space:pre-wrap}"
    page = "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>"+html.escape(title)+"</title><style>"+style+"</style><body>"+"\n".join(markup+scripts)+"</body></html>"
    return "\n".join(md), page


def generate(run, compare=None):
    run = Path(run)
    data = analyze(run)
    previous = analyze(compare) if compare else None
    markdown, page = render(data,previous)
    (run/"report.md").write_text(markdown)
    (run/"report.html").write_text(page)
    write_json(run/"summary.json", {k:v for k,v in data.items() if k not in {"system","series","breakdown"}})
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run",type=Path)
    parser.add_argument("--compare",type=Path)
    args = parser.parse_args()
    generate(args.run,args.compare)
    print(args.run/"report.html")


if __name__ == "__main__":
    main()
