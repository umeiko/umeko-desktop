"""Read a small first-sheet preview without extracting or executing workbook content."""
from pathlib import PurePosixPath
import re
import stat
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile

SHEET = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
OFFICE_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PACKAGE_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
ROW_LIMIT, COL_LIMIT, XML_LIMIT, BOOK_LIMIT = 32, 12, 4 * 1024 * 1024, 32 * 1024 * 1024
CELL = re.compile(r'([A-Z]{1,3})([1-9][0-9]{0,6})\Z')


def read_first_sheet(stream, info, cancelled):
    if not stat.S_ISREG(info.st_mode) or info.st_size > BOOK_LIMIT:
        raise ValueError('Unsupported workbook size')
    def tag(name):
        return '{' + SHEET + '}' + name
    def texts(node):
        if node is None:
            return ''
        return ''.join(t.text or '' for t in node.iter(tag('t')))
    with ZipFile(stream) as book:
        if len(book.infolist()) > 4096:
            raise ValueError('Too many workbook members')
        def xml(member):
            if cancelled():
                raise InterruptedError('Document changed')
            part = book.getinfo(member)
            if part.file_size > XML_LIMIT:
                raise ValueError('Workbook part exceeds preview limit')
            with book.open(part) as f:
                raw = f.read(XML_LIMIT + 1)
            if len(raw) > XML_LIMIT or b'\0' in raw or b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
                raise ValueError('Unsupported XML')
            return ET.fromstring(raw)
        workbook = xml('xl/workbook.xml')
        sheets = workbook.findall(f"{tag('sheets')}/{tag('sheet')}")
        if not sheets:
            raise ValueError('No worksheets')
        first = sheets[0]
        key = first.get(f'{{{OFFICE_REL}}}id')
        rel = next((row for row in xml('xl/_rels/workbook.xml.rels').findall(f'{{{PACKAGE_REL}}}Relationship')
                    if row.get('Id') == key and row.get('Type') == OFFICE_REL + '/worksheet'
                    and row.get('TargetMode') != 'External'), None)
        if not key or rel is None:
            raise ValueError('No internal worksheet')
        target = rel.get('Target', '')
        member = target.lstrip('/') if target.startswith('/') else f'xl/{target}'
        if (not member.startswith('xl/worksheets/') or '..' in PurePosixPath(member).parts
                or '\\' in member or not member.endswith('.xml')):
            raise ValueError('Unsupported worksheet path')
        sheet = xml(member)
        shared = list(xml('xl/sharedStrings.xml').iter(tag('si'))) if 'xl/sharedStrings.xml' in book.NameToInfo else []
        truncated = len(sheets) > 1
        values = {}
        for row in sheet.findall(f"{tag('sheetData')}/{tag('row')}"):
            if cancelled():
                raise InterruptedError('Document changed')
            for node in row.findall(tag('c')):
                ref = CELL.fullmatch(node.get('r', ''))
                if not ref:
                    continue
                col = 0
                for letter in ref[1]:
                    col = col * 26 + ord(letter) - 64
                rid = int(ref[2])
                if rid > ROW_LIMIT or col > COL_LIMIT:
                    truncated = True
                    continue
                val = node.findtext(tag('v'), '')
                if node.get('t') == 'inlineStr':
                    val = texts(node.find(tag('is')))
                elif node.get('t') == 's':
                    i = int(val)
                    if not 0 <= i < len(shared):
                        raise ValueError('Invalid shared string')
                    val = texts(shared[i])
                elif node.get('t') == 'b':
                    val = {'1': 'TRUE', '0': 'FALSE'}.get(val, val)
                # Display only stored values, including cached formula results.
                if len(val) > 180:
                    truncated = True
                values[(rid, col)] = val[:180]
        row_count = max((pos[0] for pos in values), default=0)
        cols = max((pos[1] for pos in values), default=0)
        rows = [[values.get((r, c), '') for c in range(1, cols + 1)] for r in range(1, row_count + 1)]
        return first.get('name', '')[:100], rows, cols, truncated


SHEET_ERRORS = (BadZipFile, ET.ParseError, ValueError, KeyError, OSError, RuntimeError)
