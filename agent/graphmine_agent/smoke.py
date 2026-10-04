from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx


class SmokeTestError(RuntimeError):
    """Raised when a live v1 acceptance invariant is not satisfied."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeTestError(message)


def run_live_smoke_test(
    *,
    base_url: str,
    api_token: str,
    graph_path: Path,
    timeout_seconds: int,
    require_llm: bool,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_token}"}
    deadline = time.monotonic() + timeout_seconds
    request_timeout = max(30.0, float(timeout_seconds))
    with httpx.Client(
        base_url=base_url.rstrip("/"),
        headers=headers,
        timeout=httpx.Timeout(request_timeout, connect=10.0),
    ) as client:
        health: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            try:
                response = client.get("/api/health")
                if response.status_code == 200:
                    health = response.json()
                    if health.get("graphmine", {}).get("binary_available") and (
                        not require_llm or health.get("llm", {}).get("available")
                    ):
                        break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        _require(health is not None, "API health endpoint did not become available")
        _require(
            health["graphmine"]["binary_available"]
            and not health["graphmine"].get("error"),
            f"GraphMine is not ready: {health['graphmine'].get('error')}",
        )
        _require(health.get("version") == "1.0.0", "agent is not version 1.0.0")
        _require(
            health["graphmine"].get("library_version") == health["version"],
            "agent and native GraphMine versions do not match",
        )
        if require_llm:
            _require(health["llm"]["enabled"], "LLM is disabled")
            _require(health["llm"]["available"], "LLM endpoint is unavailable")

        domains = client.get("/api/domains")
        domains.raise_for_status()
        _require(
            any(item["id"] == "general" for item in domains.json()),
            "general domain is missing",
        )
        session_response = client.post(
            "/api/sessions",
            json={"domain_id": "general", "title": "GraphMine v1 live smoke"},
        )
        session_response.raise_for_status()
        session = session_response.json()

        with graph_path.open("rb") as graph_file:
            upload = client.post(
                f"/api/sessions/{session['id']}/files",
                files={"file": (graph_path.name, graph_file, "application/json")},
                data={"role": "graph", "directed": "false"},
            )
        upload.raise_for_status()
        graph = upload.json()
        _require(
            graph.get("metadata", {}).get("vertex_count") == 3,
            "triangle graph metadata was not preserved",
        )

        chat = client.post(
            f"/api/sessions/{session['id']}/chat",
            json={
                "message": (
                    "Enumerate every maximal clique in this graph and include the "
                    "exact total count."
                ),
                "graph_id": graph["id"],
                "mode": "auto",
                "execute": True,
            },
        )
        chat.raise_for_status()
        response = chat.json()
        _require(response.get("plan") is not None, "planner returned no plan")
        _require(
            response["plan"]["operation_id"] == "maximal-cliques",
            f"planner chose {response['plan']['operation_id']!r}",
        )
        job_id = response.get("job_id")
        _require(bool(job_id), "chat did not queue a GPU job")

        job: dict[str, Any] = {}
        while time.monotonic() < deadline:
            job_response = client.get(f"/api/jobs/{job_id}")
            job_response.raise_for_status()
            job = job_response.json()
            if job["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.25)
        _require(job.get("status") == "completed", f"GPU job ended as {job}")
        result_response = client.get(f"/api/results/{job['result_id']}")
        result_response.raise_for_status()
        result = result_response.json()
        _require(result["payload"].get("ok") is True, "native result is not successful")
        _require(
            result["payload"].get("output", {}).get("returned_count") == 1,
            "triangle maximal-clique result is incorrect",
        )
        interpretation = result.get("interpretation")
        _require(interpretation is not None, "analyst returned no interpretation")
        _require(bool(interpretation.get("evidence")), "analyst returned no evidence")
        _require(
            bool(interpretation.get("visualizations")),
            "analyst returned no visualization",
        )

        followup = client.post(
            f"/api/sessions/{session['id']}/chat",
            json={
                "message": (
                    "Explain what this result establishes and cite the exact result "
                    "field without running another computation."
                ),
                "result_id": result["id"],
                "mode": "auto",
                "execute": True,
            },
        )
        followup.raise_for_status()
        followup_body = followup.json()
        _require(followup_body.get("mode") == "analyst", "follow-up did not stay in analyst mode")
        _require(not followup_body.get("job_id"), "interpretation follow-up queued a new job")
        return {
            "status": "passed",
            "base_url": base_url,
            "model": health["llm"]["model"],
            "operation_id": result["operation_id"],
            "backend": result["payload"].get("provenance", {}).get("backend"),
            "job_id": job_id,
            "result_id": result["id"],
            "compiled_backend_count": health["graphmine"][
                "compiled_backend_count"
            ],
            "backend_policy_loaded": health["graphmine"].get(
                "backend_policy_loaded", False
            ),
        }
