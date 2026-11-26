"""通过真实 LiteLLM 代理记录参数转换和自动探测结果。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class FakeVLLM:
    """仅由收到的字段决定输出；未知顶层 thinking 保持默认行为。"""

    def __init__(self, answer):
        self.requests = []
        self.answer = answer
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def send_json(self, body, status=200):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self.send_json({"object": "list", "data": [{"id": "test-model", "object": "model"}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                record = {"path": self.path, "body": body}
                owner.requests.append(record)
                amounts = {"none": 0, "minimal": 50, "low": 50, "medium": 75,
                           "high": 75, "xhigh": 75, "max": 100}
                effort = body.get("reasoning_effort")
                if effort is not None and effort not in amounts:
                    record.update(status=400, reasoningTokens=0)
                    return self.send_json({"error": {"type": "BadRequestError", "param": "reasoning_effort",
                        "message": "reasoning_effort: Input should be 'none', 'minimal', 'low', 'medium', 'high', 'xhigh' or 'max'"}}, 400)
                amount = amounts.get(effort, 75)
                template = body.get("chat_template_kwargs") or {}
                if type(template.get("thinking")) is bool:
                    amount = 75 if template["thinking"] else 0
                cap = int(body.get("max_tokens", body.get("max_completion_tokens", 4096)))
                amount = min(amount, cap)
                answer = owner.answer if cap > amount else ""
                finish = "stop" if answer else "length"
                record.update(status=200, reasoningTokens=amount, answer=answer, finishReason=finish)
                usage = {"prompt_tokens": 20, "completion_tokens": amount + bool(answer),
                         "total_tokens": 20 + amount + bool(answer),
                         "completion_tokens_details": {"reasoning_tokens": amount}}
                if not body.get("stream"):
                    return self.send_json({"id": "chatcmpl-fixture", "object": "chat.completion", "created": 1,
                        "model": "test-model", "choices": [{"index": 0, "finish_reason": finish,
                        "message": {"role": "assistant", "content": answer, "reasoning_content": "r " * amount}}],
                        "usage": usage})
                chunks = []

                def chunk(delta, finish_reason=None, usage_value=None):
                    value = {"id": "chatcmpl-fixture", "object": "chat.completion.chunk", "created": 1,
                             "model": "test-model", "choices": [{"index": 0, "delta": delta,
                             "finish_reason": finish_reason}]}
                    if usage_value is not None:
                        value["usage"] = usage_value
                    chunks.append("data: " + json.dumps(value) + "\n\n")

                chunk({"role": "assistant"})
                if amount:
                    chunk({"reasoning_content": "r " * amount})
                if answer:
                    chunk({"content": answer})
                chunk({}, finish)
                chunks.append("data: " + json.dumps({"id": "chatcmpl-fixture", "object": "chat.completion.chunk",
                    "created": 1, "model": "test-model", "choices": [], "usage": usage}) + "\n\n")
                chunks.append("data: [DONE]\n\n")
                raw = "".join(chunks).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def wait_ready(process, port, timeout=90):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"LiteLLM exited with code {process.returncode}")
        try:
            with opener.open(f"http://127.0.0.1:{port}/health/liveliness", timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(.25)
    raise TimeoutError("LiteLLM readiness deadline exceeded")


def run(output):
    from app.gateway import Gateway
    from app.integration import UnconfiguredAdapter
    from app import reasoning_detection

    python = os.environ.get("LITELLM_PYTHON")
    if not python:
        raise ValueError("Set LITELLM_PYTHON to an environment containing LiteLLM 1.108.4 proxy dependencies")
    output.mkdir(parents=True, exist_ok=False)
    answer = str(reasoning_detection.PROBE_ANSWER)
    result = {"routes": {}, "status": "running"}
    process = None
    with tempfile.TemporaryDirectory(prefix="profiles-", dir=output) as temporary, FakeVLLM(answer) as upstream:
        profile = Path(temporary)
        port = free_port()
        config = {"model_list": [
            {"model_name": alias, "litellm_params": {"model": f"{provider}/test-model",
             "api_base": f"http://127.0.0.1:{upstream.server.server_port}/v1", "api_key": "fixture-key"}}
            for alias, provider in (("deepseek-route", "deepseek"), ("hosted-route", "hosted_vllm"))],
            "litellm_settings": {"telemetry": False, "num_retries": 0},
            "general_settings": {"master_key": "fixture-master"}}
        config_path = profile / "proxy.yaml"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        env = dict(os.environ)
        env.update(LITELLM_LOCAL_MODEL_COST_MAP="True", LITELLM_TELEMETRY="False",
                   LITELLM_DONT_SHOW_FEEDBACK_BOX="True", NO_PROXY="localhost,127.0.0.1,::1",
                   no_proxy="localhost,127.0.0.1,::1", PYTHONIOENCODING="utf-8")
        command = [python, "-c", "import sys; from importlib.metadata import version; assert version('litellm') == '1.108.4'; from litellm.proxy.proxy_cli import run_server; sys.exit(run_server())",
                   "--config", str(config_path), "--host", "127.0.0.1", "--port", str(port)]
        try:
            with (output / "proxy.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(command, cwd=profile, env=env, stdout=log, stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                result["proxyPid"] = process.pid
                wait_ready(process, port)
                for alias in ("deepseek-route", "hosted-route"):
                    model = {"alias": alias, "upstream": alias, "reasoningLevelsAuto": True,
                             "reasoningFormatAuto": True}
                    provider = {"id": alias, "name": "Fixture", "api": "openai", "key": "fixture-master",
                                "baseUrl": f"http://127.0.0.1:{port}/v1", "models": [model]}
                    store = SimpleNamespace(directory=profile / alias, data={"providers": [provider]})
                    store.directory.mkdir()
                    gateway = Gateway(store, UnconfiguredAdapter())
                    start = len(upstream.requests)
                    detection = gateway.detect_reasoning(alias)
                    route = {"detection": detection, "probeRequestCount": len(upstream.requests) - start,
                             "probeRequests": upstream.requests[start:]}
                    result["routes"][alias] = route
                    model.update(reasoningLevels=detection["levels"].get("levels", []),
                                 reasoningFormat=detection["format"].get("format", "openai"),
                                 reasoningDetection=detection["levels"], reasoningFormatDetection=detection["format"])
                    normal = []
                    levels = model["reasoningLevels"] or [detection["format"].get("onEffort") or "high"]
                    for effort in [*levels, "off"]:
                        before = len(upstream.requests)
                        completion = gateway.complete(alias, [{"role": "user", "content": "Fixture normal chat"}],
                            max_tokens=512, parameters={"_umeko_reasoning_effort": effort})
                        normal.append({"effort": effort, "content": completion.text,
                            "reasoningChars": len(completion.thinking), "wireRequests": upstream.requests[before:]})
                    route["normalChat"] = normal
                    write_json(output / "results.json", result)
                result["status"] = "passed"
                verify(result)
        except BaseException as error:
            result.update(status="failed", error=f"{type(error).__name__}: {error}")
            raise
        finally:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                result["proxyExitCode"] = process.returncode
            result["upstreamRequestCount"] = len(upstream.requests)
            write_json(output / "results.json", result)
            write_json(output / "upstream-requests.json", upstream.requests)
    print(json.dumps({"status": result["status"], "requestCount": result["upstreamRequestCount"]}))


def verify(result):
    deepseek = result["routes"]["deepseek-route"]
    hosted = result["routes"]["hosted-route"]
    assert deepseek["detection"]["format"]["format"] == "template-thinking", deepseek["detection"]
    assert len(deepseek["detection"]["levels"]["levels"]) <= 1, deepseek["detection"]
    assert hosted["detection"]["format"]["format"] == "openai-none", hosted["detection"]
    assert hosted["detection"]["levels"]["levels"] == ["none", "low", "high", "max"], hosted["detection"]
    for route in (deepseek, hosted):
        assert route["detection"]["format"]["offVerified"], route["detection"]
        for chat in route["normalChat"]:
            assert chat["content"], chat
            assert len(chat["wireRequests"]) == 1, chat
            assert bool(chat["reasoningChars"]) == (chat["effort"] not in ("off", "none")), chat
    for record in deepseek["probeRequests"]:
        assert "reasoning_effort" not in record["body"], record


def reclassify(source):
    """复用原始观测应用新的分组规则，保留原运行与普通聊天证据。"""
    from app.reasoning_detection import detect_model

    result = json.loads(source.read_text(encoding="utf-8"))
    calls = {}
    for alias, route in result["routes"].items():
        captured = {(item["level"], item["format"], item["outputCap"]): item
                    for item in route["detection"]["levels"]["evidence"]}
        replayed = []

        def request(effort, style, cap):
            key = (effort, style, cap)
            if key not in captured:
                raise RuntimeError(f"Missing captured observation: {key}")
            row = captured[key]
            replayed.append({"effort": effort, "format": style, "outputCap": cap})
            if not row["accepted"]:
                raise ValueError(row["error"])
            return {name: row.get(name) for name in ("reasoningTokens", "thinkingChars", "answer",
                    "finishReason", "thinking", "content", "correct")}

        route["originalDetection"] = route["detection"]
        route["detection"] = detect_model(request)
        calls[alias] = replayed
    result["offlineReclassification"] = {
        "source": source.name, "method": "Exact observed amount grouping, using captured callback observations",
        "networkRequests": 0, "replayedCallbacks": calls,
        "normalChatScope": "Original real proxy run; newly selected low level has probe evidence only"}
    verify(result)
    destination = source.with_name("reclassified-results.json")
    write_json(destination, result)
    print(json.dumps({"status": "passed", "networkRequests": 0,
        "routes": {name: {"format": row["detection"]["format"]["format"],
                          "levels": row["detection"]["levels"]["levels"],
                          "replayedCallbacks": len(calls[name])} for name, row in result["routes"].items()}}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output-dir", type=Path)
    mode.add_argument("--reclassify-from", type=Path)
    args = parser.parse_args()
    if args.reclassify_from:
        reclassify(args.reclassify_from)
    else:
        run(args.output_dir)
