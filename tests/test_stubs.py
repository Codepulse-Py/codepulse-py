import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from models.serving import vllm_stub
from sandbox import server as sandbox_server


@pytest.fixture
def serve():
    servers = []

    def start(handler):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def _get(url):
    with urllib.request.urlopen(url) as resp:
        return resp.status, json.loads(resp.read())


def test_sandbox_health(serve):
    base = serve(sandbox_server.Handler)
    assert _get(f"{base}/health") == (200, {"status": "ok", "service": "sandbox"})


def test_sandbox_unknown_route(serve):
    base = serve(sandbox_server.Handler)
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{base}/nope")
    assert exc.value.code == 404


def test_vllm_stub_lists_model(serve):
    base = serve(vllm_stub.Handler)
    status, body = _get(f"{base}/v1/models")
    assert status == 200
    assert body["data"][0]["id"] == vllm_stub.MODEL_NAME


def test_vllm_stub_chat_completion(serve):
    base = serve(vllm_stub.Handler)
    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())
    assert body["choices"][0]["message"]["role"] == "assistant"
