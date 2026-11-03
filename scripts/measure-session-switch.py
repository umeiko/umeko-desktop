#!/usr/bin/env python3
"""Local, offscreen native-Pi/Controller/QML benchmark; never calls a model.

Run: .venv/Scripts/python.exe scripts/measure-session-switch.py --label baseline
This is deliberately outside CI. Fixtures and the catalog-only Pi projection
are held in one TemporaryDirectory and removed after shutdown.
"""
from __future__ import annotations

import argparse
import cProfile
import faulthandler
import gc
import inspect
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import textwrap
import types
import re
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", UMEKO_LANGUAGE="zh")

import psutil
from PySide6.QtCore import QProcess, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow, QQuickTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.controller import Controller
from app.integration import Completion
from app.pi_runtime import CATALOG, PACKAGE, node_executable
from app.syntax_highlight import register_text_types
import shiboken6


class IdealProvider:
    ready = True
    calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        return Completion("Test response", input_tokens=1, output_tokens=1)


def wait(predicate, timeout=45):
    end = time.perf_counter() + timeout
    while not predicate():
        if time.perf_counter() >= end:
            raise TimeoutError("Offscreen benchmark condition timed out")
        # QTest.qWait in this PySide/Python build can starve Python worker
        # threads. Explicitly release the GIL while pumping Qt's owner thread.
        QApplication.processEvents()
        time.sleep(0.001)


def descendants(item):
    todo = [item]
    while todo:
        child = todo.pop()
        yield child
        todo.extend(child.childItems())


def fixture(path, sid, count, language, workspace):
    """Exactly count visible user/assistant messages, with native tool entries."""
    rows = [{"type": "session", "version": 3, "id": sid,
             "timestamp": "2026-11-03T00:00:00.000Z", "cwd": str(workspace)}]
    parent = None
    prose = "中文会话切换测量，保留代码、表格和工具结果。" if language == "zh" else "Session switching measurement preserves code, tables and tool results."
    for n in range(count):
        uid = f"m{n}"
        content = [{"type": "text", "text": f"{prose} {n}\n\n```python\ndef example(x):\n    return x + 1\n```\n\n| key | value |\n| --- | --- |\n| sample | 123 |\n"}]
        role = "user" if n % 2 == 0 else "assistant"
        if role == "assistant" and n % 10 == 9:
            content.append({"type": "toolCall", "id": f"call{n}", "name": "read", "arguments": {"path": "test-data.txt"}})
        message = {"role": role, "content": content, "timestamp": 1793664000000 + n}
        if role == "assistant":
            message.update(api="openai-completions", provider="umeko", model="test-model", stopReason="stop",
                           usage={"input": 1, "output": 1, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 2,
                                  "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}})
        rows.append({"type": "message", "id": uid, "parentId": parent,
                     "timestamp": "2026-11-03T00:00:00.000Z", "message": message})
        parent = uid
        if role == "assistant" and n % 10 == 9:
            resultid = f"r{n}"
            rows.append({"type": "message", "id": resultid, "parentId": parent,
                         "timestamp": "2026-11-03T00:00:00.000Z", "message": {
                             "role": "toolResult", "toolCallId": f"call{n}", "toolName": "read", "isError": False,
                             "timestamp": 1793664000000 + n, "content": [{"type": "text", "text": (prose + " line\n") * 160}]}})
            parent = resultid
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return {"id": sid, "file": str(path), "title": f"Test {language} {count}",
            "workspace": str(workspace), "model": "test-model", "provider": "test-provider"}


def prepare_runtime(temp):
    """Reuse installed SDK; change only the provider catalog, as normal packaging does."""
    # Copying the entire module tree is unnecessary for this local measurement.
    # Its catalog files use the same provider-only projection used by
    # app.pi_runtime.project_runtime and are restored after the run.
    modules = ROOT / "runtime/node_modules"
    ai = modules / "@earendil-works/pi-ai/dist"
    saved = {}
    for rel, value in {"providers/all.js": CATALOG,
                       "models.generated.js": "export const MODELS = {};\nexport const IMAGE_MODELS = {};\nexport const CLASSIFIER_MODELS = {};\n"}.items():
        target = ai / rel
        saved[target] = target.read_bytes()
        target.write_text(value, encoding="utf-8")
    return ROOT / "runtime", saved


def one_controller(temp, release):
    os.environ["UMEKO_DATA_DIR"] = str(temp / "data")
    workspace = temp / "workspace"
    agent = temp / "agent"
    workspace.mkdir(parents=True)
    agent.mkdir()
    provider = IdealProvider()
    controller = Controller(ROOT)
    controller._release = release
    controller.toast.connect(lambda message: print("TOAST " + message, flush=True))
    controller.adapter = controller.gateway.adapter = provider
    controller.store.data.update(selectedProvider="test-provider", selectedModel="test-model", providers=[{
        "id": "test-provider", "name": "Test provider", "api": "internal", "baseUrl": "", "key": "",
        "models": [{"upstream": "test-model", "alias": "test-model", "contextWindow": 128000}]}])
    controller.store.data["agent"].update(agentDir=str(agent), autoCompaction=False, safeMode=True)
    controller.setWorkspace(QUrl.fromLocalFile(str(workspace)).toString())
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", controller)
    engine.load(QUrl.fromLocalFile(str(ROOT / "app/qml/Main.qml")))
    if not engine.rootObjects():
        raise RuntimeError("Main.qml did not load")
    window = engine.rootObjects()[0]
    window.setWidth(1300)
    window.setHeight(1000)
    window.setProperty("page", "chat")
    QTest.qWait(20)
    return controller, engine, window, provider, workspace


def render(controller, window):
    # Include actual virtual ListView delegates, asynchronous page preparation,
    # QML text/layout and software scenegraph rasterization of Main.qml.
    model = controller.messageModel
    last = model.rowCount() - 1
    if last >= 0:
        model.requestRange(max(0, last - 3), last)
        wait(lambda: all(model.isReady(i) for i in range(max(0, last - 3), last + 1)))
    for _ in range(3):
        QApplication.processEvents()
    image = window.grabWindow()
    if image.isNull():
        raise RuntimeError("Offscreen software scenegraph returned a null frame")


def measure(controller, window, sid, scenario):
    start = time.perf_counter()
    controller.openSession(sid)
    try:
        wait(lambda: controller.activeSession == sid)
    except TimeoutError:
        faulthandler.dump_traceback()
        preview = controller._session_preview
        print("PREVIEW " + repr({"active": controller.activeSession, "requested": sid, "request": preview.request,
                                "direct_token": preview.direct_token, "reading": preview.reading, "prepared": preview.prepared,
                                "pending": preview.pending}), flush=True)
        raise
    history = time.perf_counter()
    render(controller, window)
    rendered = time.perf_counter()
    events = []
    callback = lambda record, event: events.append((time.perf_counter(), event.get("type"), event.get("message", ""))) if record is controller._view else None
    controller._pool.event.connect(callback)
    record = controller._view
    already_ready = bool(record.process and record.ready)
    kernel_start = time.perf_counter()
    try:
        if not controller._command_pi("inspect"):
            raise RuntimeError("Native kernel inspect was rejected")
        wait(lambda: any(kind == "done" for _, kind, _ in events))
        errors = [message for _, kind, message in events if kind == "error"]
        if errors:
            raise RuntimeError("Native Pi initialization failed: " + "; ".join(errors))
        kernel_ready = kernel_start if already_ready else next(t for t, kind, _ in events if kind == "ready")
        done = next(t for t, kind, _ in events if kind == "done")
        render(controller, window)
        return {"scenario": scenario, "history_load_ms": (history - start) * 1000,
                "render_ms": (rendered - history) * 1000, "browse_total_ms": (rendered - start) * 1000,
                "kernel_start_resume_ms": (kernel_ready - kernel_start) * 1000,
                "native_inspect_total_ms": (done - kernel_start) * 1000,
                "kernel_was_cached": already_ready, "native_pid": int(record.process.processId())}
    finally:
        controller._pool.event.disconnect(callback)


def memory_sample(controller):
    nodes = []
    for record in controller._pool.records.values():
        if record.process and record.ready:
            pid = int(record.process.processId())
            nodes.append({"session_id": record.id, "pid": pid, "rss_bytes": psutil.Process(pid).memory_info().rss})
    return {"python_qml_rss_bytes": psutil.Process().memory_info().rss,
            "node_rss_bytes": sum(row["rss_bytes"] for row in nodes), "nodes": nodes}


def measure_memory(temp, release, capacity):
    case = temp / "memory"
    case.mkdir()
    controller, engine, window, provider, workspace = one_controller(case, release)
    try:
        if capacity is not None:
            if not controller.setSessionCacheSize(capacity):
                raise RuntimeError("Session cache capacity setting was rejected")
        render(controller, window)
        gc.collect()
        empty = memory_sample(controller)
        stages = []
        for index, language in enumerate(("zh", "en", "zh")):
            row = fixture(case / f"long-{index}.jsonl", f"memory-{index}", 500, language, workspace)
            controller._sessions.append(row)
            measure(controller, window, row["id"], "memory")
            gc.collect()
            stages.append(memory_sample(controller))
        controller.newSession()
        render(controller, window)
        # Retirement is asynchronous; wait for the exact retired processes the
        # pool owns, never discover or stop unrelated processes.
        wait(lambda: not controller._pool.retiring)
        gc.collect()
        blank = memory_sample(controller)
        if provider.calls:
            raise RuntimeError("Memory measurement unexpectedly requested inference")
        return {"scenario": "visit three native Pi sessions with 500 visible messages each (zh/en/zh), then switch to blank",
                "cache_capacity": capacity,
                "model_calls": provider.calls,
                "empty_controller": empty, "after_each_session": stages,
                "after_switch_blank": blank,
                "python_qml_delta_bytes": blank["python_qml_rss_bytes"] - empty["python_qml_rss_bytes"],
                "node_delta_bytes": blank["node_rss_bytes"] - empty["node_rss_bytes"],
                "limits": "RSS is a point sample. Python and QML share one process and are reported together. Empty-to-visited delta includes index/history work; compare fresh capacity0/3 end states for cache overhead. Python allocator may retain freed pages, so RSS is not exact retained object size. Does not measure sustained growth or compare shared pages across processes."}
    finally:
        controller.close()
        window.close()
        shiboken6.delete(engine)
        shiboken6.delete(controller)
        QApplication.processEvents()
        gc.collect()


def profile_cached(temp, release):
    """One new diagnostic sample, not a repeated matrix or acceptance gate."""
    case = temp / "profile"
    case.mkdir()
    controller, engine, window, provider, workspace = one_controller(case, release)
    stages = {}
    def timed(name, function, *args, **kwargs):
        start = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            value = stages.setdefault(name, {"calls": 0, "total_ms": 0.0})
            value["calls"] += 1
            value["total_ms"] += (time.perf_counter() - start) * 1000
    try:
        target = fixture(case / "target.jsonl", "profile-target", 500, "zh", workspace)
        other = fixture(case / "other.jsonl", "profile-other", 10, "zh", workspace)
        controller._sessions.extend([target, other])
        measure(controller, window, target['id'], "profile_warmup")
        controller.openSession(other['id'])
        wait(lambda: controller.activeSession == other['id'])
        render(controller, window)
        original = controller._activate
        source = textwrap.dedent(inspect.getsource(original))
        source = re.sub(r"self\.(\w+)\.emit\(([^\n]*)\)",
                        lambda match: f"_profile_timed('signal.{match[1]}', lambda: self.{match[1]}.emit({match[2]}))", source)
        namespace = dict(original.__func__.__globals__, _profile_timed=timed)
        exec(compile(source, "<profile-activate-signals>", "exec"), namespace)
        profiler = cProfile.Profile()
        with ExitStack() as stack:
            stack.enter_context(patch.object(controller, '_activate', types.MethodType(namespace['_activate'], controller)))
            for owner, method, name in [(controller._pool, 'touch', 'pool.touch'),
                                        (controller._pool, 'trim', 'pool.trim'),
                                        (controller._pool, 'trim_bodies', 'pool.trim_bodies'),
                                        (controller.store, 'save', 'store.save'),
                                        (controller._chat_model, 'set_session', 'model.set_session'),
                                        (controller._chat_model, 'set_snapshot', 'model.set_snapshot'),
                                        (controller._chat_model, 'update', 'model.update')]:
                function = getattr(owner, method)
                stack.enter_context(patch.object(owner, method, lambda *args, _function=function, _name=name, **kwargs: timed(_name, _function, *args, **kwargs)))
            profiler.enable()
            start = time.perf_counter()
            controller.openSession(target['id'])
            wait(lambda: controller.activeSession == target['id'])
            active = time.perf_counter()
            render(controller, window)
            finished = time.perf_counter()
            profiler.disable()
        profiler.dump_stats(str(case / 'cached.prof'))
        entries = []
        for entry in profiler.getstats():
            code = entry.code
            name = code if isinstance(code, str) else f"{Path(code.co_filename).name}:{code.co_firstlineno}:{code.co_name}"
            entries.append({'function': name, 'calls': entry.callcount, 'cumulative_ms': entry.totaltime * 1000,
                            'own_ms': entry.inlinetime * 1000})
        if provider.calls:
            raise RuntimeError("Profiling unexpectedly requested inference")
        return {'scenario': 'one zh500 cached return after real native inspect warmup',
                'history_activation_ms': (active - start) * 1000, 'render_ms': (finished - active) * 1000,
                'stages': stages, 'profile_cumulative': sorted(entries, key=lambda row: row['cumulative_ms'], reverse=True)[:40],
                'profile_own': sorted(entries, key=lambda row: row['own_ms'], reverse=True)[:25], 'model_calls': provider.calls}
    finally:
        controller.close()
        window.close()
        shiboken6.delete(engine)
        shiboken6.delete(controller)
        QApplication.processEvents()
        gc.collect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--observations", type=int, default=5)
    parser.add_argument("--counts", type=int, nargs="+", default=[10, 100, 500])
    parser.add_argument("--languages", nargs="+", default=["zh", "en"])
    parser.add_argument("--resume-log", type=Path)
    parser.add_argument("--memory-only", action="store_true")
    parser.add_argument("--cache-size", type=int)
    parser.add_argument("--profile-cached", action="store_true")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    register_text_types()
    observations = []
    if args.resume_log:
        for line in args.resume_log.read_text(encoding="utf-8").splitlines():
            if line.startswith('{"scenario":'):
                observations.append(json.loads(line))
    result = {"label": args.label, "source_revision": os.environ.get("UMEKO_MEASUREMENT_SOURCE_REV", "unspecified"), "observations_per_cell": args.observations,
              "environment": {"platform": sys.platform, "python": sys.version.split()[0], "qt_platform": "offscreen",
                              "renderer": "software", "node": Path(node_executable()).name, "pi": "1.3.0", "window": [1300, 1000]},
              "method": "Real Controller.openSession, PiSessionPool QProcess, pinned native Pi bridge/SDK, Main.qml software frame. Separate read-only browse from explicit inspect (no prompt/model call). Controlled evicted scenario calls pool.retire, the same lifecycle used by LRU trim, and drops only the inactive SessionState to force disk history reload.",
              "limits": ["Offscreen software rasterization; no visible desktop input or frame-to-display latency.",
                         "First-open is application-cold per unique fixture, not OS disk-cache cold.",
                         "Kernel resume metric is zero for an already-ready process; inspect roundtrip is reported separately.",
                         "Native initialization contains real resource discovery; provider is ideal local fixture and no inference occurs."],
              "raw": observations}
    saved = {}
    with tempfile.TemporaryDirectory(prefix="umeko-issue60-measure-") as rawtemp:
        temp = Path(rawtemp)
        print("FIXTURE_DIRECTORY " + str(temp), flush=True)
        release, saved = prepare_runtime(temp)
        # Force hidden subprocesses below native Node helpers. No shell or model
        # operation is requested by inspect, and all fixture scopes are isolated.
        preload = temp / "hidden-children.cjs"
        preload.write_text("const cp=require('node:child_process'); for(const key of ['spawn','spawnSync','execFile','execFileSync']) { const old=cp[key]; cp[key]=function(...a){let i=Array.isArray(a[1])?2:1; if(typeof a[i]==='function')a.splice(i,0,{});a[i]={...(a[i]||{}),windowsHide:true};return old.apply(this,a)} } require('node:module').syncBuiltinESMExports();", encoding="utf-8")
        class HiddenProcess(QProcess):
            def setProcessEnvironment(self, environment):
                environment.insert("NODE_OPTIONS", "--require=" + json.dumps(str(preload)))
                super().setProcessEnvironment(environment)
        try:
            with patch("app.pi_sessions.QProcess", HiddenProcess), patch("app.provider_plugins.BundledProviders.sync", return_value=[]):
                if args.memory_only:
                    result["memory"] = measure_memory(temp, release, args.cache_size)
                if args.profile_cached:
                    result["profile"] = profile_cached(temp, release)
                for language in args.languages:
                    if args.memory_only or args.profile_cached:
                        break
                    for count in args.counts:
                        if all(sum(r["language"] == language and r["messages"] == count and r["scenario"] == scenario for r in observations) >= args.observations
                               for scenario in ("first_open", "switch_back", "evicted")):
                            continue
                        case = temp / f"{language}-{count}"
                        case.mkdir()
                        controller, engine, window, provider, workspace = one_controller(case, release)
                        try:
                            for n in range(args.observations):
                                target = fixture(case / f"target-{n}.jsonl", f"target-{language}-{count}-{n}", count, language, workspace)
                                other = fixture(case / f"other-{n}.jsonl", f"other-{language}-{count}-{n}", 10, language, workspace)
                                controller._sessions.extend([target, other])
                                for scenario in ("first_open", "switch_back", "evicted"):
                                    if scenario != "first_open":
                                        controller.openSession(other["id"])
                                        wait(lambda: controller.activeSession == other["id"])
                                    if scenario == "evicted":
                                        record = controller._pool.find(target["id"])
                                        controller._pool.retire(record)
                                        controller._pool.records.pop(record.key)
                                    value = measure(controller, window, target["id"], scenario)
                                    value.update(messages=count, language=language, observation=n + 1)
                                    observations.append(value)
                                    print(json.dumps(value), flush=True)
                                # Isolate repetitions while leaving real cache
                                # behavior in each three-switch sequence intact.
                                controller._pool.retire(controller._view)
                            if provider.calls:
                                raise RuntimeError("Benchmark unexpectedly requested inference")
                        finally:
                            controller.close()
                            window.close()
                            shiboken6.delete(engine)
                            shiboken6.delete(controller)
                            QApplication.processEvents()
                            gc.collect()
        finally:
            for target, original in saved.items():
                target.write_bytes(original)
    result["medians"] = []
    for language in args.languages:
        if args.memory_only or args.profile_cached:
            break
        for count in args.counts:
            for scenario in ("first_open", "switch_back", "evicted"):
                rows = [r for r in observations if r["language"] == language and r["messages"] == count and r["scenario"] == scenario]
                result["medians"].append({"language": language, "messages": count, "scenario": scenario, "n": len(rows),
                    **{k: statistics.median(r[k] for r in rows) for k in ("history_load_ms", "render_ms", "browse_total_ms", "kernel_start_resume_ms", "native_inspect_total_ms")}})
    output = ROOT / "docs" / f"session-cache-measurements-{args.label}.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("RESULT " + str(output), flush=True)


if __name__ == "__main__":
    main()
