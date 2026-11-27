"""Per-HTTP-attempt admission for the native engine, without proxying requests.

The disposable child waits on a private Unix socket before its own HTTP call.
The parent holds the same account/model quota and power leases as planner calls.
"""

import asyncio
from contextlib import contextmanager
import json
import os
import tempfile
from pathlib import Path

import anyio
import httpx

from .accounts import _metered, _reported_usage
from .errors import AnalyticsError
from .llm_power import power_request

MAX_EVENT_BYTES = 2 * 1024 * 1024


class Admission:
    def __init__(self, runtime, provider, models, credential):
        self.runtime, self.provider, self.models = runtime, provider, set(models)
        self.credential = credential
        self.tasks = set()
        self.error = None
        self.usage = {"http_requests": 0, "prompt_tokens": 0, "completion_tokens": 0}

    async def start(self, path):
        self.server = await asyncio.start_unix_server(self.handle, path, limit=MAX_EVENT_BYTES)
        os.chmod(path, 0o600)

    async def close(self):
        self.server.close()
        await self.server.wait_closed()
        for task in tuple(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            if self.error is not None:
                raise self.error
            request = json.loads(await reader.readline())
            body = request["body"]
            if (request["base_url"] != self.provider["base_url"] or
                    body.get("model") not in self.models or body.get("temperature") != 0 or
                    body.get("chat_template_kwargs") != {"enable_thinking": False} or
                    body.get("response_format", {}).get("type") != "json_schema" or
                    body["response_format"].get("json_schema", {}).get("strict") is not True or
                    body.get("max_tokens") != 4096):
                raise AnalyticsError("The native request does not match its approved provider controls.", "semantic_controls", 503)
            headers = {"Authorization": "Bearer " + self.credential} if self.credential else {}
            async with httpx.AsyncClient(base_url=self.provider["base_url"], headers=headers,
                                        timeout=10, trust_env=False, follow_redirects=False) as client:
                async with power_request(self.runtime.settings, base=self.provider["base_url"], registry=self.runtime.llm_power):
                    async with _metered(client, "/chat/completions", body, 4096) as meter:
                        writer.write(b"ok\n")
                        await writer.drain()
                        self.usage["http_requests"] += 1
                        # EOF means cancellation/crash. Quota handling then keeps
                        # its conservative input charge, never a fabricated zero.
                        raw = await reader.readline()
                        if not raw:
                            raise asyncio.CancelledError
                        event = json.loads(raw)
                        status = event["status"]
                        if status == 200:
                            response = json.loads(event["response"])
                            usage = response.get("usage", {})
                            if meter is not None:
                                meter["used"] = _reported_usage(usage)
                            for key in ("prompt_tokens", "completion_tokens"):
                                value = usage.get(key)
                                if type(value) is int and value >= 0:
                                    self.usage[key] += value
                        elif meter is not None:
                            meter["used"] = 0 if status else None
                writer.write(b"settled\n")
                await writer.drain()
        except asyncio.CancelledError:
            pass
        except Exception as error:
            # Preserve known quota/status errors without forwarding provider text,
            # request bodies or credentials into worker output or application logs.
            if hasattr(error, "code"):
                self.error = error
            else:
                self.error = AnalyticsError("Model admission could not be completed.", "semantic_admission", 503)
            try:
                writer.write(b"denied\n")
                await writer.drain()
            except (ConnectionError, OSError):
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            self.tasks.discard(task)


@contextmanager
def admit(runtime, provider, models, credential):
    # /tmp also keeps the socket path below sockaddr_un's 108-byte limit.
    # TemporaryDirectory is 0700; no other account can connect to this socket.
    with tempfile.TemporaryDirectory(prefix="gm-admit-") as temporary:
        path = str(Path(temporary) / "admission.sock")
        gate = Admission(runtime, provider, models, credential)
        anyio.from_thread.run(gate.start, path)
        try:
            yield path, gate
        finally:
            anyio.from_thread.run(gate.close)
