"""Stand-in for the vLLM OpenAI-compatible server (stdlib only).

Lets the stack run on machines without a GPU. It mimics the handful of vLLM
routes the pipeline will call; real serving of the fine-tuned
Qwen2.5-Coder-7B adapter lands in #18.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5-coder-7b-stub")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok", "service": "vllm-stub"})
        elif self.path == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": MODEL_NAME, "object": "model"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self._send(
            200,
            {
                "object": "chat.completion",
                "model": MODEL_NAME,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"label": "none"}'},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    def _send(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    port = int(os.getenv("PORT", "8200"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
