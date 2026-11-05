"""Local synthetic history profiling; no user conversations or model requests.

Use a fresh --output for each run and the same --fixtures across revisions.
Default: cProfile the index. --gui also measures the real offscreen Qt view;
use --no-profile for comparable wall times without instrumentation overhead.
"""
from __future__ import annotations

import argparse
import cProfile
import faulthandler
import hashlib
import json
import os
import pstats
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fixture(path, turns, kind, error_chars=2_000_000):
    entries = [{'type': 'session', 'version': 3, 'id': path.stem, 'cwd': str(path.parent)}]
    parent = None

    def add(role, content, **values):
        nonlocal parent
        identifier = f'entry-{len(entries)}'
        entries.append({'type': 'message', 'id': identifier, 'parentId': parent,
                        'message': {'role': role, 'content': content, 'provider': 'fixture',
                                    'model': 'fixture', **values}})
        parent = identifier
        return identifier

    failure = '供应商返回 HTTP 503：service unavailable [Umeko:12345678-1234-1234-1234-123456789abc]'
    if kind == 'long-error':
        error = 'Provider rejected request: ' + ('error detail ' * 2000)
    elif kind == 'large-failure':
        # One unbounded upstream/extension error at the end of a long chat.
        error = 'Provider rejected request: ' + ('error detail ' * (error_chars // 13 + 1))[:error_chars]
    else:
        error = failure
    for turn in range(turns):
        add('user', f'Question {turn}: inspect this fixture and explain the result.')
        text = f'Reply {turn}.\n\n' + 'This is a representative answer with **formatted text**.\n' * 4
        content = [{'type': 'thinking', 'thinking': 'Review the requested change.\n' * 20},
                   {'type': 'text', 'text': text}]
        if turn % 5 == 0:
            call = f'call-{turn}'
            add('assistant', [*content, {'type': 'toolCall', 'id': call, 'name': 'bash',
                                        'arguments': {'command': 'echo fixture'}}])
            add('toolResult', 'fixture output\n' * 10, toolCallId=call)
        values = {'stopReason': 'stop'}
        failing = kind != 'normal' and (kind != 'large-failure' or turn == turns - 1)
        if failing:
            values.update(stopReason='aborted' if kind == 'aborted' else 'error', errorMessage=error)
        failed = add('assistant', content if not failing or kind in ('partial', 'aborted') else [], **values)
        if kind == 'recovered':
            identifier = f'entry-{len(entries)}'
            entries.append({'type': 'context_edit', 'id': identifier, 'parentId': parent,
                            'targetId': failed, 'replacement': None})
            parent = identifier
            add('assistant', content, stopReason='stop')
    path.write_text(''.join(json.dumps(entry, ensure_ascii=False) + '\n' for entry in entries), encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profile_call(path, callback, enabled=True):
    if not enabled:
        start = time.perf_counter()
        value = callback()
        return value, round((time.perf_counter() - start) * 1000, 2)
    profiler = cProfile.Profile()
    start = time.perf_counter()
    value = profiler.runcall(callback)
    seconds = time.perf_counter() - start
    profiler.dump_stats(str(path.with_suffix('.prof')))
    with path.with_suffix('.txt').open('w', encoding='utf-8') as out:
        pstats.Stats(profiler, stream=out).strip_dirs().sort_stats('cumulative').print_stats(35)
    return value, round(seconds * 1000, 2)


def source_fixture(args, turns, kind):
    directory = args.fixtures or args.output
    directory.mkdir(parents=True, exist_ok=True)
    source = (directory / f'{kind}-{turns}.jsonl').resolve()
    if not source.exists():
        fixture(source, turns, kind, args.error_chars)
    return source, hashlib.sha256(source.read_bytes()).hexdigest()


def gui_profile(args):
    os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                      UMEKO_DATA_DIR=str(args.output.resolve() / 'profile'))
    from PySide6.QtCore import QTimer, QObject, Signal
    from app.controller import Controller
    from app.chat_presentation import HistoryPresentation
    from app.transcript_index import TranscriptRepository
    from main import create_application
    import shiboken6

    profile = args.output / 'profile'
    profile.mkdir(exist_ok=True)
    (profile / 'settings.json').write_text(json.dumps({'agent': {'agentDir': str(profile.resolve() / 'agent')}}), encoding='utf-8')

    class QuietNotifications(QObject):
        activated = Signal(str)
        def __init__(self, *args):
            super().__init__()
        def close(self):
            pass
        def task_finished(self, *args):
            pass

    with patch.object(Controller, 'loadNativeIndex', lambda self: None), \
         patch('app.tray.TrayController.tray_available', lambda self: False), \
         patch('app.notifications.TaskNotifications', QuietNotifications):
        app, engine, backend = create_application()
    window = engine.rootObjects()[0]
    window.resize(1300, 1000)
    warnings, records, ticks = [], [], []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    backend.toast.connect(lambda text: print('TOAST:', text, flush=True))
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    timer.start(10)

    def items(root):
        yield root
        for child in root.childItems():
            yield from items(child)

    def find(name):
        return next((item for item in items(window.contentItem()) if item.objectName() == name), None)

    def ready(view):
        if not view or view.property('restoring') or backend.messageModel._job is not None:
            return False
        top = view.property('contentY')
        visible = [item for item in view.property('contentItem').childItems()
                   if item.property('messageSlot') is True and item.y() + item.height() > top + 2
                   and item.y() < top + view.height() - 2]
        return bool(visible) and all(item.property('bodyReady') for item in visible)

    def wait(predicate):
        start = time.perf_counter()
        while not predicate():
            if time.perf_counter() - start > 60:
                raise TimeoutError(str(warnings))
            app.processEvents()
            time.sleep(.001)

    current, stages = '', []
    open_source, prepare_source = TranscriptRepository.open, HistoryPresentation.prepare

    def open_profile(repository, *pos, **kw):
        start = time.perf_counter()
        snapshot = open_source(repository, *pos, **kw)
        ms = (time.perf_counter() - start) * 1000
        stages.append({'stage': 'index', 'ms': ms, 'parsed': snapshot.parsed_entries})
        return snapshot

    def prepare_profile(presentation, *pos, **kw):
        start = time.perf_counter()
        value = prepare_source(presentation, *pos, **kw)
        stages.append({'stage': 'presentation', 'ms': (time.perf_counter() - start) * 1000})
        return value

    try:
        with patch.object(TranscriptRepository, 'open', open_profile), \
             patch.object(HistoryPresentation, 'prepare', prepare_profile):
            backend._sessions = []
            for turns in args.turns:
                for kind in args.kinds:
                    name = f'{kind}-{turns}'
                    source, digest = source_fixture(args, turns, kind)
                    backend._sessions.append({'id': name, 'file': str(source), 'title': name, 'workspace': str(args.output.resolve())})
                    for phase in ('cold', 'retained', 'indexed'):
                        backend.newSession()
                        if phase == 'indexed':
                            record = backend._pool.find(name)
                            backend._conversation_views.discard(record.key)
                            backend._pool._clear_body(record)
                        # Drain blank-view work before starting the measured operation.
                        for _ in range(20):
                            app.processEvents()
                            time.sleep(.005)
                        current = name + '-' + phase
                        stages.clear()
                        ticks[:] = [time.perf_counter()]

                        def navigate():
                            backend.openSession(name)
                            wait(lambda: backend.activeSession == name)
                            view = find('conversation')
                            wait(lambda: ready(view))
                            window.grabWindow()

                        _, ms = profile_call(args.output / (current + '-gui'), navigate, args.profile)
                        ticks.append(time.perf_counter())
                        value = dict(kind=kind, turns=turns, phase=phase, ms=ms, profiled=args.profile,
                                     max_gui_gap_ms=round(max(b-a for a,b in zip(ticks, ticks[1:])) * 1000, 2),
                                     rows=backend.messageModel.rowCount(), prepared=len(backend.messageModel._prepared),
                                     page_cache_bytes=backend.transcripts.cache.weight, stages=list(stages), sha256=digest)
                        records.append(value)
                        (args.output / 'metrics.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
                        print(json.dumps(value), flush=True)
                    window.grabWindow().save(str(args.output / (name + '.png')))
        assert not warnings, warnings
    finally:
        timer.stop()
        backend.close()
        window.hide()
        shiboken6.delete(engine)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--turns', type=int, nargs='+', default=[600, 3000])
    parser.add_argument('--kinds', nargs='+', choices=['normal', 'failed', 'partial', 'recovered', 'aborted', 'long-error', 'large-failure'],
                        default=['normal', 'failed', 'partial', 'recovered', 'long-error'])
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--fixtures', type=Path, help='Reuse identical source bytes across revisions/runs.')
    parser.add_argument('--error-chars', type=int, default=2_000_000)
    parser.add_argument('--no-profile', dest='profile', action='store_false', help='Measure wall time without profiler overhead.')
    args = parser.parse_args()
    if any(count <= 0 for count in args.turns) or args.error_chars <= 0:
        parser.error('Fixture sizes must be positive.')
    if (args.output / 'metrics.json').exists():
        parser.error('Use a fresh output directory so cold runs do not reuse previous indexes.')
    args.output.mkdir(parents=True, exist_ok=True)
    faulthandler.dump_traceback_later(120, repeat=True)
    if args.gui:
        return gui_profile(args)
    from app.transcript_index import TranscriptRepository
    records = []
    for turns in args.turns:
        for kind in args.kinds:
            name = f'{kind}-{turns}'
            source, digest = source_fixture(args, turns, kind)
            cache = args.output / (name + '-cache')
            repository = TranscriptRepository(cache)
            for phase in ('cold', 'warm'):
                snapshot, ms = profile_call(args.output / f'{name}-{phase}', lambda: repository.open(source), args.profile)
                record = dict(kind=kind, turns=turns, phase=phase, ms=ms, rows=snapshot.count, profiled=args.profile,
                              parsed=snapshot.parsed_entries, source_bytes=source.stat().st_size,
                              cache_bytes=repository.cache.weight, sha256=digest)
                records.append(record)
                print(json.dumps(record), flush=True)
    (args.output / 'metrics.json').write_text(json.dumps(records, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
