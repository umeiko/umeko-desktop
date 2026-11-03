---
name: microsoft-office
description: Create, read, and edit Word, PowerPoint, and Excel files.
license: MIT
metadata:
  hermes:
    tags:
    - office
    - word
    - docx
    - powerpoint
    - pptx
    - excel
    - xlsx
    - csv
    - documents
    - slides
    - spreadsheets
    category: productivity
    related_skills:
    - pdf
  version: 2.0.0
  author: Nous Research
  platforms:
  - linux
  - macos
  - windows
---
> Umeko adaptation, 2026-11-01. Use Pi Agent's available `read`, `write`,
> `edit` and `bash` tools rather than another harness's tool names. Resolve
> helper and reference paths from this SKILL.md directory; write deliverables
> in the user's task workspace. Show finished artifacts with
> `submit_to_chatbox` tool (consult its actual tool schema).
> Dependencies below are prerequisites, not a claim that they are installed.



# Microsoft Office Skill

Create, read, edit, and template Word (`.docx`), PowerPoint (`.pptx`), and
Excel (`.xlsx`, `.csv`) files offline with small Python CLIs built on
python-docx, python-pptx, and openpyxl. Office itself is never needed. It does
not open legacy binary formats (`.doc`, `.ppt`, `.xls`) and does not render
pages without LibreOffice.

## When to Use

Pick the format, then read its reference with `read` before working:

| File | Reference | Typical asks |
| --- | --- | --- |
| `.docx` | `references/word.md` | reports, letters, contracts, `{{token}}` templates, tracked changes, comments |
| `.pptx` | `references/powerpoint.md` | pitch decks, brand-template decks, chart refreshes, speaker notes, slide PNGs |
| `.xlsx`, `.csv` | `references/excel.md` | styled multi-sheet workbooks, formulas, charts, CSV conversion, row/column restructures |

Deeper notes: `references/revisions-and-comments.md` (Word review markup) and
`references/restructuring.md` (Excel reference shifting).

- Not for `.doc`/`.ppt`/`.xls`: convert first with
  `soffice --headless --convert-to docx|pptx|xlsx old-file` when LibreOffice is installed.
- Not for `.odt`/`.odp`/`.ods`, or WYSIWYG layout work.

## Prerequisites and preflight

Use a user-accessible Python 3.10+ interpreter; a frozen Umeko executable is
not a general-purpose Python CLI. If the task already has a `.umeko-tools`
environment, use its interpreter. Otherwise choose the task's existing Python,
and do not assume that the desktop's packaged environment contains these packages.
Set `PY` to that interpreter and check once per task environment:

```bash
"$PY" -c "import sys, importlib.metadata as m; print(sys.version); [print(p, m.version(p)) for p in ('python-docx', 'python-pptx', 'openpyxl')]"
command -v soffice || command -v libreoffice
command -v pdftoppm
```

The required package versions are `python-docx==1.2.0`,
`python-pptx==1.0.2`, and `openpyxl==3.1.5`. LibreOffice is needed only for PDF
conversion and formula recalculation; Poppler is needed for PNG render checks.
Report missing versions and which operations are unavailable, and continue only
the supported parts. Never claim an unperformed conversion or render.

If installation is needed, explain the proposed environment and obtain explicit
user authorization first. Create or reuse a task-local `.umeko-tools` virtual
environment for Python packages, then rerun the checks. Use
`.umeko-tools/bin/python` on Unix or `.umeko-tools/Scripts/python.exe` on
Windows. Do not modify Umeko's packaged environment or global Python packages.

On a restricted or corporate network, reuse user-confirmed package indexes,
proxy settings, and CA certificates supported by the selected installer. Model
provider proxy settings do not configure pip, uv, system package managers, or
browser downloads. Do not guess internal URLs or treat a public mirror as an
approved internal source. Prefer command- or task-scoped settings over global
proxy, registry, or pip changes; preserve TLS verification and redact credentials.
Confirm proxy and CA settings separately on remote hosts and in containers:
the office machine's loopback proxy is not automatically valid there.

Helpers live in this Skill folder's `scripts/`; call them by absolute path
from the task workspace and inspect `--help` before choosing arguments.

## How to Run

Every helper lives in `scripts/`, is an argparse CLI with `--help`, prints
JSON to stdout, and exits non-zero on failure. Run them with `bash` from
the skill directory. Author JSON specs with `write_file`; read results with
`read_file` or straight from stdout.

```bash
"$PY" scripts/docx_create.py spec.json out.docx
"$PY" scripts/pptx_create.py deck.json out.pptx
"$PY" scripts/xlsx_create.py spec.json report.xlsx
```

## Quick Reference

| Task | Word | PowerPoint | Excel |
| --- | --- | --- | --- |
| Create from JSON spec | `docx_create.py` | `pptx_create.py` | `xlsx_create.py`, `csv_to_xlsx.py` |
| Read back | `docx_read.py --text/--structure` | `pptx_read.py --outline` | `xlsx_read.py --sheets/--json` |
| Edit | `docx_edit.py` | `pptx_edit.py` | `xlsx_edit.py`, `xlsx_restructure.py` |
| Fill a template | `docx_template.py` | `pptx_from_template.py` | — |
| Review / check | `docx_revisions.py`, `docx_comments.py`, `docx_validate.py` | `pptx_render.py` (slide PNGs) | `xlsx_recalc.py`, `xlsx_to_csv.py` |

The per-format reference has the full flag table.

## Procedure

1. Identify the format from the file extension or the ask, and load its
   reference (`skill_view` with `file_path=references/<format>.md`).
2. Set `PY` with the Prerequisites block once per session.
3. Create, edit, or read with that format's helpers; pass an output path to
   keep the original whenever the helper supports one.
4. Verify the result as the reference's Verification section says, then give
   the user the exact output path.

## Converting to PDF

When LibreOffice is installed, convert headlessly:

```bash
soffice --headless --convert-to pdf --outdir out/ file.docx   # also .pptx, .xlsx
soffice --headless --convert-to csv --outdir out/ report.xlsx # first sheet only
```

Check first with `command -v soffice || command -v libreoffice`. Fonts not on
the host are substituted, so render-check decks before shipping. There is no
pure-Python path to PDF for any of these formats: if `soffice` is missing, say
so rather than approximating. For other sheets use
`xlsx_to_csv.py --sheet NAME`.

## Pitfalls

- **Never unzip-and-edit the XML.** These files are zip packages; raw text
  substitution corrupts them. Edit through the helpers (or the libraries) and
  use `patch`/`write_file` only for JSON inputs.
- **Text is split into runs.** Word and PowerPoint fragment text at edit
  boundaries; the replace helpers merge equal-format runs first, but a match
  across differently formatted runs takes the first run's formatting.
- **Nothing computes fields or formulas.** Word TOC/page fields and Excel
  formulas are filled in by the office app on open (or by `xlsx_recalc.py`).
- **Encoding.** Write specs as UTF-8; the helpers read UTF-8 explicitly.
- Format-specific traps are in each reference.

## Verification

- Re-read every output with the format's read helper and check the expected
  content is there and the old content is gone.
- Word: `docx_validate.py out.docx` exits 0 after revision, comment, or field
  surgery.
- PowerPoint: render with `pptx_render.py` and check each PNG with
  `vision_analyze` when the render tools exist.
- Excel: `xlsx_read.py --formulas` lists written formulas; run
  `xlsx_recalc.py` when cached values matter.
- The bundled tests are the full contract:
  `"$PY" -m pytest tests/ -q` (needs pytest in that interpreter).

## Multi-format delivery and visual checks

For PDF export, requested page/range previews, formula caches, or concurrent
LibreOffice processes, read [delivery checks](references/delivery-checks.md),
adapted from DeepSeek Harness skill-office. The DSH SDK/sidecar is not required.
