# Office delivery checks

Umeko adaptation (2026-11-01) of DeepSeek Harness skill-office's Office,
rendering, PDF export and recalculation workflow. Source: commit
ce7073d51254c26cd63b22a60835b8f948deb447 of deepseek-ai/deepseek-harness,
packages/skill/skill-office/assets/. MIT notice retained in
../licenses/deepseek-harness-MIT.txt. This portable adaptation uses the installed
system LibreOffice and the Python helpers; the DSH SDK and its LibreOffice Kit
sidecar are not bundled. Do not call DSH-only tools or placeholder Node paths.

## Save and verify the requested source

Deliver the format the user requested. Preserve the editable source even when
also exporting PDF or preview images. Reopen the saved file with the relevant
Python reader to check content and structure. For a workbook check formula
text and computed values separately; writing formulas does not compute them.
Do not claim recalculation just because a file was saved successfully.

## Render or export when it helps the requested task

Check `soffice --version` (or `libreoffice --version`) before conversion.
If absent, explain that content and structure were checked but visual export
requires LibreOffice. Do not install a system application without appropriate
user authorization. Work in a uniquely named temporary directory inside the
task workspace, with an isolated LibreOffice profile per concurrent process.
Use absolute paths, quote each path, set a bounded process timeout, and retain
the original source. A typical PDF conversion is:

```text
soffice -env:UserInstallation=file:///ABSOLUTE/PRIVATE/profile --headless --convert-to pdf --outdir /ABSOLUTE/PRIVATE/output /ABSOLUTE/source.docx
```

Use a real file URI for the private profile (e.g. `Path(...).as_uri()` in Python),
not a string assembled by replacing spaces. Run through `subprocess.run` with
an argument list and `timeout=120` rather than shell interpolation. Reuse
existing previews for an unchanged source. For DOCX/PPTX/PDF inspect the
requested pages/slides; for XLSX inspect the exact sheet/range and include
charts. Change print areas or scaling only if the user requested print layout.
Use Poppler to render exported PDF pages when available. Inspect images only
if the current model can view them; an image export alone is not visual QA.

Check clipping, headings, tables, fonts, chart labels and number formats. A
blank/transparent image from populated content is a failed visual check.
Report that limitation rather than claiming the layout passed. LibreOffice
rendering can differ from Microsoft Office and does not verify animations,
media playback, external-data refresh or unsupported features.

## Recalculate worksheets without overwriting the original

Use scripts/xlsx_recalc.py after inspecting its `--help`. It requires system
LibreOffice. Reopen the recalculated copy twice: `data_only=False` to retain
formula expressions and `data_only=True` to inspect cached results. Check the
affected sheets for formula errors and missing caches, and distinguish these
from deliberately blank cells. Do not replace failed/missing formula caches
with guessed numbers. Preserve the source and any external-link limitations.

## Deliver

Report what was actually verified and any unmet dependencies. Submit the final
editable file and requested exports using `submit_to_chatbox`. Keep delivered
files in place; remove only this task's private inspection directory after
inspection, and never link to deleted previews.
