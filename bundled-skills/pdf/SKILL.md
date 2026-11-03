---
name: pdf
description: Use when tasks involve reading, creating, or reviewing PDF files where
  rendering and layout matter; prefer visual checks by rendering pages (Poppler) and
  use Python tools such as `reportlab`, `pdfplumber`, and `pypdf` for generation and
  extraction.
metadata: {}
---
> Umeko adaptation, 2026-11-01. Use Pi Agent's available `read`, `write`,
> `edit` and `bash` tools rather than another harness's tool names. Resolve
> helper and reference paths from this SKILL.md directory; write deliverables
> in the user's task workspace. Show finished artifacts with
> `submit_to_chatbox` tool (consult its actual tool schema).
> Dependencies below are prerequisites, not a claim that they are installed.




# PDF Skill

## When to use
- Read or review PDF content where layout and visuals matter.
- Create PDFs programmatically with reliable formatting.
- Validate final rendering before delivery.

## Workflow
1. Prefer visual review: render PDF pages to PNGs and inspect them.
   - Use `pdftoppm` if available.
   - If unavailable, install Poppler or ask the user to review the output locally.
2. Use `reportlab` to generate PDFs when creating new documents.
3. Use `pdfplumber` (or `pypdf`) for text extraction and quick checks; do not rely on it for layout fidelity.
4. After each meaningful update, re-render pages and verify alignment, spacing, and legibility.

## Temp and output conventions
- Use `tmp/pdfs/` for intermediate files; delete when done.
- Write final artifacts under `output/pdf/` when working in this repo.
- Keep filenames stable and descriptive.

## Dependencies and preflight

Use a user-accessible Python 3.10+ interpreter, not the frozen Umeko executable.
If the task already has a `.umeko-tools` environment, use its interpreter;
otherwise use the task's existing Python. Set `PY` to the selected interpreter
and check the actual environment before generating or extracting:

```bash
"$PY" -c "import sys, importlib.metadata as m; print(sys.version); [print(p, m.version(p)) for p in ('reportlab', 'pdfplumber', 'pypdf')]"
command -v pdftoppm
```

Use `reportlab>=4`, `pdfplumber>=0.10`, and `pypdf>=3`. Report a missing or
incompatible package instead of assuming it is available. If Poppler is absent,
explain that visual rendering is unverified; use another available review path
or ask the user to inspect the PDF locally rather than claiming a visual check.

If installation is needed, describe the missing dependency and target
environment, then obtain explicit user authorization before installing anything.
Prefer a task-local `.umeko-tools` virtual environment and an already available
`uv` or pip; do not modify Umeko's packaged environment or global Python packages.
Install Poppler through the operating system's approved package source only after
authorization. Rerun the same checks after installation.

For a restricted or corporate network, reuse user-confirmed package indexes,
proxy settings, and CA certificates supported by the selected tool. Model
provider proxy settings do not configure pip, uv, or system package managers.
Do not guess internal URLs or treat a public mirror as an approved internal
source. Prefer command- or task-scoped settings over global configuration changes,
preserve TLS verification, and redact credentials. Confirm proxy and CA settings
separately on remote hosts and in containers; a loopback proxy on the office
machine is not automatically valid there.

If installation is not possible, tell the user exactly what is missing, which
operations remain possible, and how to complete the setup locally.

## Environment
No required environment variables.

## Rendering command
```
pdftoppm -png $INPUT_PDF $OUTPUT_PREFIX
```

## Quality expectations
- Maintain polished visual design: consistent typography, spacing, margins, and section hierarchy.
- Avoid rendering issues: clipped text, overlapping elements, broken tables, black squares, or unreadable glyphs.
- Charts, tables, and images must be sharp, aligned, and clearly labeled.
- Use ASCII hyphens only. Avoid U+2011 (non-breaking hyphen) and other Unicode dashes.
- Citations and references must be human-readable; never leave tool tokens or placeholder strings.

## Final checks
- Do not deliver until the latest PNG inspection shows zero visual or formatting defects.
- Confirm headers/footers, page numbering, and section transitions look polished.
- Keep intermediate files organized or remove them after final approval.
