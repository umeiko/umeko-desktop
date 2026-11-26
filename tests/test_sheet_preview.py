import os
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from app.document_preview import document_kind, read_preview
from app.sheet_preview import SHEET, OFFICE_REL, PACKAGE_REL


class SheetPreviewTests(unittest.TestCase):
    def write(self, path, content, target='worksheets/sheet.xml', mode='', shared=None):
        with ZipFile(path, 'w') as z:
            z.writestr('xl/workbook.xml', f'<workbook xmlns="{SHEET}" xmlns:r="{OFFICE_REL}"><sheets><sheet name="区域" r:id="r1"/></sheets></workbook>')
            z.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="{PACKAGE_REL}"><Relationship Id="r1" Type="{OFFICE_REL}/worksheet" Target="{target}" {mode}/></Relationships>')
            z.writestr('xl/worksheets/sheet.xml', content)
            if shared:
                z.writestr('xl/sharedStrings.xml', shared)

    def test_values_and_bounds(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / 'report.xlsx'
            self.write(p, f'<worksheet xmlns="{SHEET}"><sheetData>'
                '<row><c r="A1" t="s"><v>0</v></c><c r="B1"><f>SUM(2,3)</f><v>5</v></c></row>'
                '<row><c r="B2" t="inlineStr"><is><t>&lt;b&gt;plain&lt;/b&gt;</t></is></c></row>'
                '<row><c r="A50"><v>100</v></c></row></sheetData></worksheet>',
                shared=f'<sst xmlns="{SHEET}"><si><r><t>华</t></r><r><t>东</t></r></si></sst>')
            before = p.read_bytes()
            state = read_preview(str(p), 'xlsx')
            self.assertEqual(state['sheetRows'], [['华东', '5'], ['', '<b>plain</b>']])
            self.assertEqual(state['sheetName'], '区域')
            self.assertTrue(state['truncated'])
            self.assertEqual(p.read_bytes(), before)
            self.assertEqual(document_kind(str(p)), '')  # No new auto-open path.

    def test_ignores_external_parts_and_rejects_xml_entities(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / 'report.xlsx'
            self.write(p, '<unused/>', target='https://example.invalid/file',
                       mode='TargetMode="External"')
            self.assertTrue(read_preview(str(p), 'xlsx')['error'])
            self.write(p, '<!DOCTYPE worksheet [<!ENTITY a "test">]><worksheet/>')
            self.assertTrue(read_preview(str(p), 'xlsx')['error'])
            self.write(p, '<worksheet/>')
            with self.assertRaises(InterruptedError):
                read_preview(str(p), 'xlsx', cancelled=lambda: True)

    @unittest.skipUnless(os.name == 'posix', 'FIFO requires POSIX')
    def test_nonregular_file_is_not_read(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / 'report.xlsx'
            os.mkfifo(p)
            self.assertTrue(read_preview(str(p), 'xlsx')['error'])
