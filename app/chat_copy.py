"""Render selected plain text in a worker, including unloaded display pages."""
import json
import zlib
from PySide6.QtGui import QTextDocument
from PySide6.QtQml import QJSEngine

from .transcript_index import connect, StaleIndex


def selected_text(script, snapshot, overlay, anchor, cursor, expanded):
    def order(value):
        return value['row'], value['block'], value['offset']
    start, end = sorted((anchor, cursor), key=order)
    engine = QJSEngine()
    result = engine.evaluate(script.replace('.pragma library', '', 1))
    if result.isError():
        raise RuntimeError(result.toString())
    document, pieces = QTextDocument(), []
    base = snapshot.count if snapshot else 0

    def append(row, message):
        expression = 'selectionSegments(' + json.dumps(message) + ',' + str(row) + ',' + json.dumps(expanded) + ')'
        value = engine.evaluate(expression)
        if value.isError():
            raise RuntimeError(value.toString())
        for segment in value.toVariant():
            if segment.get('markdown'):
                formatted = engine.evaluate('forQt(' + json.dumps(segment['text']) + ')').toString()
                document.setMarkdown(formatted)
            else:
                document.setPlainText(segment['text'])
            text = document.toPlainText()
            raw = text.encode('utf-16-le', errors='surrogatepass')
            first, last = (row, segment['block'], 0), (row, segment['block'], len(raw) // 2)
            if last <= order(start) or first >= order(end):
                continue
            lo = start['offset'] if first < order(start) else 0
            hi = end['offset'] if last > order(end) else len(raw) // 2
            selected = raw[lo * 2:hi * 2].decode('utf-16-le', errors='surrogatepass')
            if segment.get('copyPrefix') and (start['row'] < row or start['block'] < segment['block']):
                document.setMarkdown(segment['copyPrefix'])
                prefix = document.toPlainText()
                if selected.startswith(prefix):
                    selected = selected[len(prefix):]
            if segment.get('copyJoin') and pieces:
                pieces[-1] += ('' if segment['copyJoin'] == 'direct' or pieces[-1].endswith('\n') else '\n') + selected
            else:
                pieces.append(selected)

    if snapshot and start['row'] < base:
        # One read transaction gives the copy a consistent branch while Pi can
        # append and the index writer can publish its next revision in WAL.
        with connect(snapshot.database) as db:
            db.execute('BEGIN')
            revision = db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
            if int(revision) != snapshot.revision:
                raise StaleIndex('聊天内容已更新，请重新选择后复制')
            rows = db.execute('SELECT seq,body,continuation FROM display WHERE seq>=? AND seq<=? ORDER BY seq', (start['row'], min(base - 1, end['row'])))
            for row in rows:
                message = json.loads(zlib.decompress(row['body']))
                message['continuation'] = bool(row['continuation'])
                append(row['seq'], message)
    for row in range(max(base, start['row']), min(base + len(overlay), end['row'] + 1)):
        append(row, overlay[row - base])
    return '\n\n'.join(pieces).replace('\u2029', '\n').replace('\u2028', '\n')
