"""Controlled loopback provider shared by native and browser acceptance."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

@contextmanager
def provider(status=200, *, usage=None):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.endswith("/tokenize"):
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"count":100}')
                return
            calls.append({"body": body, "authorization": self.headers.get("Authorization")})
            code = status(len(calls)) if callable(status) else status
            rows = [{"id": i, "answer": "negative", "keep": True} for i in range(16)]
            data = {"choices": [{"message": {"content": json.dumps({"results": rows})}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120} if usage is None else usage}
            self.send_response(code); self.end_headers(); self.wfile.write(json.dumps(data).encode())
        def do_GET(self):
            self.send_response(404); self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls
    finally:
        server.shutdown(); server.server_close(); thread.join()

