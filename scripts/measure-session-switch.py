#!/usr/bin/env python3
"""Local, offscreen native-Pi/Controller/QML benchmark; never calls a model.

Run: .venv/Scripts/python.exe scripts/measure-session-switch.py --mode switches --label local
Modes: switches (nine first/cached observations), sequence (five saved sessions), memory.
This is deliberately outside CI. Fixtures and the catalog-only Pi projection
are held in one TemporaryDirectory and removed after shutdown.
"""
from __future__ import annotations

import argparse
import faulthandler
import gc
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
import threading
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
QML_ROOT = ROOT / 'app/qml'
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", UMEKO_LANGUAGE="zh")

import psutil
from PySide6.QtCore import QObject, QProcess, QUrl, Slot
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow, QQuickTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.controller import Controller
from app.integration import Completion
from app.pi_runtime import CATALOG, node_executable
from app.syntax_highlight import register_text_types
import shiboken6


class IdealProvider:
    ready = True
    calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        return Completion("Test response", input_tokens=1, output_tokens=1)


PHASES = None


class PhaseProbe(QObject):
    """High-resolution optional probes used only in instrumented task snapshots."""
    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.values = {}

    @Slot(result=float)
    def begin(self):
        return time.perf_counter()

    @Slot(str, float)
    def end(self, name, started):
        elapsed = (time.perf_counter() - started) * 1000
        with self.lock:
            value = self.values.setdefault(name, {"calls": 0, "ms": 0.0})
            value['calls'] += 1
            value['ms'] += elapsed

    @Slot(str)
    def created(self, name):
        with self.lock:
            value = self.values.setdefault(name, {"calls": 0, "ms": None})
            value['calls'] += 1

    def snapshot(self):
        with self.lock:
            return {key: dict(value) for key, value in self.values.items()}


def prepare_profile_qml(temp):
    """Instrument an isolated QML copy with the same optional timing probes."""
    destination = temp / 'qml'
    shutil.copytree(ROOT / 'app/qml', destination)
    file = destination / 'MessageBody.qml'
    text = file.read_text(encoding='utf-8')
    text = text.replace('Markdown.blocks(root.text, root.markdown, root.compact)', 'root.measuredBlocks()')
    text = text.replace('Markdown.forQt(modelData.text)', 'root.measuredForQt(modelData.text)')
    text = text.replace('    property string text: ""', '''    Component.onCompleted: measurementProbe.created("message_body_created")
    function measuredBlocks() {
        var started=measurementProbe.begin(); var result=Markdown.blocks(root.text,root.markdown,root.compact)
        measurementProbe.end("qml_markdown_blocks",started); return result
    }
    function measuredForQt(text) {
        var started=measurementProbe.begin(); var result=Markdown.forQt(text)
        measurementProbe.end("qml_markdown_forQt",started); return result
    }
    property string text: ""''')
    text = text.replace('            required property int index', '            required property int index\n            Component.onCompleted: measurementProbe.created("message_block_delegate_created")')
    file.write_text(text, encoding='utf-8')
    return destination


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
    if PHASES is not None:
        engine.rootContext().setContextProperty("measurementProbe", PHASES)
    engine.load(QUrl.fromLocalFile(str(QML_ROOT / "Main.qml")))
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


def measure_switch(controller, window, sid, scenario, **metadata):
    # Settle prior background work before resetting counters. This is outside
    # the measured switch and is identical for both revision snapshots.
    wait(lambda: controller.messageModel._job is None)
    PHASES.reset()
    started = time.perf_counter()
    controller.openSession(sid)
    wait(lambda: controller.activeSession == sid)
    activated = time.perf_counter()
    model = controller.messageModel
    last = model.rowCount() - 1
    if last >= 0:
        model.requestRange(max(0, last - 3), last)
        wait(lambda: all(model.isReady(index) for index in range(max(0, last - 3), last + 1)))
    prepared = time.perf_counter()
    for _ in range(3):
        QApplication.processEvents()
    polished = time.perf_counter()
    frame = window.grabWindow()
    finished = time.perf_counter()
    if frame.isNull():
        raise RuntimeError('Measurement offscreen frame is null')
    return {'scenario': scenario, 'session_id': sid, 'history_activation_ms': (activated - started) * 1000,
            'page_readiness_ms': (prepared - activated) * 1000,
            'qt_delegate_layout_events_ms': (polished - prepared) * 1000,
            'software_grab_ms': (finished - polished) * 1000,
            'render_ms': (finished - activated) * 1000,
            'browse_total_ms': (finished - started) * 1000,
            'phases': PHASES.snapshot(), 'background_prepare_inflight_at_frame': model._job is not None,
            **metadata}


def noise_summary(rows, keys):
    grouped = {}
    for row in rows:
        key = tuple(row.get(name) for name in keys)
        grouped.setdefault(key, []).append(row)
    result = []
    for key, values in grouped.items():
        entry = dict(zip(keys, key))
        entry['n'] = len(values)
        for field in ('history_activation_ms', 'page_readiness_ms', 'qt_delegate_layout_events_ms', 'software_grab_ms', 'render_ms', 'browse_total_ms'):
            numbers = [row[field] for row in values]
            quartiles = statistics.quantiles(numbers, n=4, method='inclusive') if len(numbers) > 1 else [numbers[0]] * 3
            entry[field] = {'median': statistics.median(numbers), 'q1': quartiles[0], 'q3': quartiles[2],
                            'iqr': quartiles[2] - quartiles[0], 'min': min(numbers), 'max': max(numbers)}
        phase_names = sorted({name for row in values for name in row['phases']})
        entry['phase_medians'] = {name: {'calls': statistics.median(row['phases'].get(name, {}).get('calls', 0) for row in values),
              'ms': None if all(row['phases'].get(name, {}).get('ms') is None for row in values) else
                    statistics.median(row['phases'].get(name, {}).get('ms', 0) or 0 for row in values)} for name in phase_names}
        result.append(entry)
    return result


def measure_mode(temp, release, args):
    global PHASES
    PHASES = PhaseProbe()
    rows = []
    details = {}
    from app.chat_presentation import HistoryPresentation
    original_prepare = HistoryPresentation.prepare
    def prepare(instance, *values, **options):
        started = time.perf_counter()
        try:
            return original_prepare(instance, *values, **options)
        finally:
            PHASES.end('python_history_prepare_inclusive', started)
    def close(controller, engine, window):
        controller.close()
        window.close()
        shiboken6.delete(engine)
        shiboken6.delete(controller)
        QApplication.processEvents()
        gc.collect()
    with patch.object(HistoryPresentation, 'prepare', prepare):
        if args.mode == 'switches':
            for language in args.languages:
                for count in args.counts:
                    case = temp / f'{language}-{count}'
                    case.mkdir()
                    controller, engine, window, provider, workspace = one_controller(case, release)
                    try:
                        other = fixture(case / 'other.jsonl', f'other-{language}-{count}', 10, language, workspace)
                        controller._sessions.append(other)
                        for observation in range(args.observations):
                            target = fixture(case / f'target-{observation}.jsonl', f'target-{language}-{count}-{observation}', count, language, workspace)
                            controller._sessions.append(target)
                            rows.append(measure_switch(controller, window, target['id'], 'first_open', language=language, messages=count, observation=observation + 1))
                            # Warm presentation fully, then visit another saved
                            # session. No Pi inspect is performed in this matrix.
                            wait(lambda: controller.messageModel._job is None)
                            controller.openSession(other['id'])
                            wait(lambda: controller.activeSession == other['id'])
                            render(controller, window)
                            rows.append(measure_switch(controller, window, target['id'], 'cached_return', language=language, messages=count, observation=observation + 1))
                        if provider.calls:
                            raise RuntimeError('Measurement unexpectedly called a model')
                    finally:
                        close(controller, engine, window)
            group = ['language', 'messages', 'scenario']
        else:
            case = temp / args.mode
            case.mkdir()
            controller, engine, window, provider, workspace = one_controller(case, release)
            try:
                if args.cache_size is not None:
                    controller.setSessionCacheSize(args.cache_size)
                details['configured_capacity'] = controller._pool.limit
                gc.collect()
                details['empty_rss'] = memory_sample(controller)
                sessions = []
                visits = 5 if args.mode == 'sequence' else args.visits
                for index in range(visits):
                    language = 'zh' if index % 2 == 0 else 'en'
                    row = fixture(case / f'saved-{index}.jsonl', chr(65 + index), 100 if args.mode == 'sequence' else 500, language, workspace)
                    sessions.append(row)
                    controller._sessions.append(row)
                for row in sessions:
                    # One native init per saved session models used history;
                    # subsequent browsing does not add synthetic inspect work.
                    measure(controller, window, row['id'], 'native_warmup')
                if args.mode == 'sequence':
                    controller.openSession('A')
                    wait(lambda: controller.activeSession == 'A')
                    render(controller, window)
                    recency = ['B', 'C', 'D', 'E', 'A']
                    for round_number in range(5):
                        for sid in ['B', 'C', 'D', 'E', 'A']:
                            rank = len(recency) - recency.index(sid)
                            rows.append(measure_switch(controller, window, sid, 'pure_five_cycle', round=round_number + 1, recency_rank=rank, rank_group='fourth_fifth'))
                            recency.remove(sid); recency.append(sid)
                    # A separate probe phase leaves the pure five-cycle intact.
                    # Rank is selected from current full recency immediately
                    # before each switch, so the probes disclose their effects.
                    for round_number in range(5):
                        for rank in [2, 3, 4, 5]:
                            sid = recency[-rank]
                            rows.append(measure_switch(controller, window, sid, 'explicit_rank_probe', round=round_number + 1, recency_rank=rank,
                                                        rank_group='recent_top3' if rank <= 3 else 'fourth_fifth'))
                            recency.remove(sid); recency.append(sid)
                    group = ['scenario', 'rank_group']
                    details['ordering'] = 'Warm A B C D E, return A; five rounds of B C D E A (every revisit rank5). Then five separate probe rounds selecting ranks2,3,4,5 from current recency before each switch. Rank1 is not a switch and is excluded.'
                else:
                    controller.newSession()
                    render(controller, window)
                    wait(lambda: not controller._pool.retiring)
                    gc.collect()
                    details['after_visits_then_blank_rss'] = memory_sample(controller)
                    details['visits'] = visits
                    details['messages_per_session'] = 500
                    details['retained_records'] = [{'id': record.id, 'loaded': record.loaded,
                                                    **({'retained': record.retained} if hasattr(record, 'retained') else {}),
                                                    'body_bytes': record.body_bytes, 'message_rows': len(record.messages), 'history_rows': len(record.history),
                                                    'tree_rows': len(record.tree), 'native_ready': bool(record.process and record.ready)} for record in controller._pool.records.values() if record.id]
                    group = []
                if provider.calls:
                    raise RuntimeError('Measurement unexpectedly called a model')
            finally:
                close(controller, engine, window)
    return {'raw': rows, 'noise_summary': noise_summary(rows, group) if rows else [], 'details': details,
            'model_calls': 0, 'phase_limits': ['QML markdown blocks/forQt bindings are directly timed via snapshot-only probes.',
              'Python HistoryPresentation.prepare includes cache lookup, markdown parsing and Qt document conversion; worker time can overlap GUI time.',
              'Qt delegate creation is counted, not separately timed. Qt binding/delegate construction, internal Text markdown-to-document conversion, font work and layout are inseparable within synchronous activation/event dispatch; qt_delegate_layout_events_ms is a combined event phase, not a direct isolated layout measurement.',
              'software_grab_ms includes any final deferred scenegraph/polish work plus software rasterization/capture, so it is not pure raster CPU time.',
              'First available frame may precede completion of background rich formatting.']}


def main():
    global QML_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=['switches', 'sequence', 'memory'])
    parser.add_argument('--label', required=True)
    parser.add_argument('--observations', type=int, default=9)
    parser.add_argument('--counts', type=int, nargs='+', default=[10, 100, 500])
    parser.add_argument('--languages', nargs='+', default=['zh', 'en'])
    parser.add_argument('--cache-size', type=int)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'artifacts/session-switch-measurements')
    parser.add_argument('--visits', type=int, default=8)
    parser.add_argument('--profile-phases', action='store_true', help='time QML parser bindings and count delegates in a temporary QML copy')
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    register_text_types()
    result = {'label': args.label, 'mode': args.mode,
              'source_revision': os.environ.get('UMEKO_MEASUREMENT_SOURCE_REV', 'unspecified'),
              'observations_per_cell': args.observations, 'profile_phases': args.profile_phases,
              'environment': {'platform': sys.platform, 'python': sys.version.split()[0],
                              'qt_platform': 'offscreen', 'renderer': 'software',
                              'node': Path(node_executable()).name, 'pi': '1.3.0', 'window': [1300, 1000]},
              'method': 'Real Controller.openSession and Main.qml software frames. Switch matrix is read-only with no inspect per switch. Sequence/memory initialize each saved native Pi once, then browse without inspect per switch.',
              'limits': ['Offscreen rendering does not measure frame-to-display latency.',
                         'First-open is application-cold per unique fixture, not OS disk-cache cold.',
                         'Ideal local Test provider/test-model; no inference or real API call.']}
    saved = {}
    with tempfile.TemporaryDirectory(prefix='umeko-session-measure-') as rawtemp:
        temp = Path(rawtemp)
        if args.profile_phases:
            QML_ROOT = prepare_profile_qml(temp)
        release, saved = prepare_runtime(temp)
        preload = temp / 'hidden-children.cjs'
        preload.write_text("const cp=require('node:child_process'); for(const key of ['spawn','spawnSync','execFile','execFileSync']) { const old=cp[key]; cp[key]=function(...a){let i=Array.isArray(a[1])?2:1; if(typeof a[i]==='function')a.splice(i,0,{});a[i]={...(a[i]||{}),windowsHide:true};return old.apply(this,a)} } require('node:module').syncBuiltinESMExports();", encoding='utf-8')
        class HiddenProcess(QProcess):
            def setProcessEnvironment(self, environment):
                environment.insert('NODE_OPTIONS', '--require=' + json.dumps(str(preload)))
                super().setProcessEnvironment(environment)
        try:
            with patch('app.pi_sessions.QProcess', HiddenProcess), patch('app.provider_plugins.BundledProviders.sync', return_value=[]):
                result['measurements'] = measure_mode(temp, release, args)
        finally:
            for target, original in saved.items():
                target.write_bytes(original)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f'session-cache-measurements-{args.label}.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('RESULT ' + str(output), flush=True)


if __name__ == '__main__':
    main()
