import json
import os
from http.server import BaseHTTPRequestHandler

import agent


class handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            length = int(self.headers.get("content-length", 0) or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            messages = body.get("messages", [])
            if not messages:
                return self._send(400, {"error": "no messages"})
            trace = []
            raw, _ = agent.respond(messages, trace=trace)
            text = agent.strip_thinking(raw)
            self._send(200, {
                "text": text,
                "score": agent.extract_score(text),
                "trace": trace,
                "usage": agent.usage(),
            })
        except RuntimeError as e:
            self._send(429, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": f"{type(e).__name__}: {e}"})
