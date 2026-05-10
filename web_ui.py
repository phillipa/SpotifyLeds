"""HTTP server for the LED control web UI.

The server is intentionally agnostic about state management — it takes three
callables that handle synchronization themselves:

  get_state()         -> dict   (current settings + enum metadata)
  apply_patch(patch)  -> dict   (mutates state from a JSON patch, returns new state)
  randomize()         -> dict   (re-rolls mode/palette/color, returns new state)

Plus a path to the static index.html that the page is served from.
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler


def make_handler(get_state, apply_patch, randomize, index_html_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # silence default access logging

        def _send_json(self, code, body):
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                try:
                    with open(index_html_path, "rb") as f:
                        body = f.read()
                except FileNotFoundError:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"index.html missing")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/state":
                self._send_json(200, get_state())
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/state":
                length = int(self.headers.get("Content-Length", 0))
                try:
                    patch = json.loads(self.rfile.read(length))
                except json.JSONDecodeError:
                    self._send_json(400, {"error": "bad json"})
                    return
                self._send_json(200, apply_patch(patch))
            elif self.path == "/randomize":
                self._send_json(200, randomize())
            else:
                self.send_response(404)
                self.end_headers()

    return Handler


def serve(host, port, get_state, apply_patch, randomize, index_html_path):
    """Build an HTTPServer wired to the given callables. Caller drives serve_forever."""
    handler = make_handler(get_state, apply_patch, randomize, index_html_path)
    return HTTPServer((host, port), handler)
