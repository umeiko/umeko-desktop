# Failed-history loading profile (#101)

Measured on 2026-11-05 against Python edition `a4225c7` (latest `origin/main`
when fetched), then the same revision with this fix. All conversations are
synthetic; no personal transcripts or external model requests were used.

## Reproduction and cause

Ordinary short failures did **not** reproduce the reported severe slowdown.
The earlier quadratic branch scan is already fixed on main. A separate
quadratic payload expansion remains when an upstream/native error is large.

`ChatModel.project()` builds the visible error activity but also leaves the
entire original `errorMessage` on its output row. `display_fragments()` splits
the visible text into 24,000-character chunks while copying that original
field into every fragment. An 8,000,027-character error produces 334 fragments,
each retaining another full error string. The index serializes and compresses
2,688,102,255 bytes of JSON for that one error (16,087,225 after the fix).
Paging then decompresses those
copies again, quickly filling the 64 MiB page cache.

The fix consumes `errorMessage` when projecting a **copy** of the native row.
The full visible error text, partial reply, and diagnostic ID remain available.
Original JSONL and in-memory native messages are unchanged. Index schema 7
rebuilds schema 6 caches so previously inflated display rows are also replaced.

## Controlled timings

Windows 11, CPython 3.12.14, PySide6/Qt 6.10.2, 1300×1000 offscreen software
rendering. Each fixture has 3,000 turns (6,000 user/assistant messages), plus
600 tool-call/tool-result pairs. The large-error fixture replaces only the
last reply with an 8 MB error. Normal and short-failure histories are controls.
The same source files and SHA-256 hashes were reused before and after.

Each timing below is the median of three fresh-process runs, with profiling
**disabled**. Cold means a fresh derived index, not a cold OS filesystem cache.
Completion waits for visible message bodies and captures a Qt frame; it is
not a physical-display latency measurement or a production performance claim.

| Scenario | Before | After |
| --- | ---: | ---: |
| Normal history, cold open | 821 ms | 825 ms |
| Short failures, cold open | 810 ms | 857 ms |
| Single 8 MB failure, cold open | 14,429 ms | 829 ms |
| Single 8 MB failure, indexed reopen after view eviction | 1,074 ms | 188 ms |
| Single 8 MB failure, retained-view return | 47 ms | 52 ms |
| Page-cache weight after the large-error open | 64,371,898 bytes | 1,145,620 bytes |
| Maximum GUI timer gap during large-error cold open (median) | 155 ms | 97 ms |

Large-error cold-open ranges were 14,397–14,546 ms before and 772–913 ms after.
Normal controls are substantially unchanged; small differences with three
samples are not evidence of universal speedup. The page-cache metric is the
existing Python object-weight accounting, **not** total process RSS. Only 4
display rows were prepared at the fixed large-error viewport.

## Profiling evidence

A separate, single-threaded index cProfile run isolates the hot path without
mixing GUI/worker timing attribution:

| Operation | Before | After |
| --- | ---: | ---: |
| `TranscriptRepository.open` | 13.717 s | 0.927 s |
| JSON serialization (`json.dumps`, cumulative) | 8.710 s | 0.108 s |
| `zlib.compress` | 3.134 s | 0.090 s |

Both profiles use exactly the same 12,825,983-byte source file, SHA-256
`167a0f248997e382da081e7f649084162b48ab0383fb5869bfe0c31248efc364`.
The broader exploratory profiles also cover partial replies, retry/context
edits, 26 KB error bodies, and 600/3,000-turn histories. They do not establish
that every instance of #101 has this same cause; a short-error-only report
would require its own reproduction.

## Reproduce locally

After normal development setup, from the repository root:

```powershell
# Capture the index call profile and a shared source fixture.
.venv/Scripts/python.exe scripts/profile-failed-history.py --output artifacts/issue-101/index-before --fixtures artifacts/issue-101/fixtures --turns 3000 --kinds normal failed large-failure --error-chars 8000000
# Capture uninstrumented Qt wall times. Use a new output directory for each run.
.venv/Scripts/python.exe scripts/profile-failed-history.py --gui --no-profile --output artifacts/issue-101/timing-before-1 --fixtures artifacts/issue-101/fixtures --turns 3000 --kinds normal failed large-failure
# Repeat on the fixed revision using the SAME --fixtures and fresh --output paths.
```

`metrics.json` records wall time, source hashes, parsed-entry counts, prepared
row counts, cache weight, and GUI timer gaps. Profiled runs also write `.prof`
files and cumulative-time text summaries. GUI runs write viewport PNGs.
No timings are used as CI assertions.

## Validation

The two added regressions fail on the original code: a 280 KB error expands
to 3.92 MB of serialized fragments. They pass with the fix, checking bounded
payload growth, complete reconstructed error text, unchanged source bytes,
and rebuilding a seeded schema 6 cache.

55 focused tests passed across failed-history loading, ChatModel, transcript
indexing, compaction, subagent history, provider errors, and dynamic QML
loading. The dynamic UI test covered nine fast-scroll/reversal sequences,
expanded tools, and retained controls, with no empty settled viewport. The
2,400-message history-window smoke also passed saved-position restoration,
background formatting, and cancellation of obsolete jumps.

The Pi Widget cold-start smoke (success/failure/no idle polling) and six Node
Widget catalog/message tests passed with the locally prepared Pi 1.3.0 bridge.
The Windows portable build and `ci-smoke.py --preview` also passed: packaged
GUI rendering, native notifications, bundled Node/search tools, terminal PTY
and cleanup, Pi self-test, and build provenance. A native-window preview with
an isolated synthetic profile was launched and visually checked. These are
local results; no CI result or released fix is implied.

Raw local evidence is retained under `artifacts/issue-101/`: `comparison.json`,
`timing-before-{1,2,3}/metrics.json`, `timing-after-{1,2,3}/metrics.json`,
`8mb-index-before/`, `8mb-index-after/`, and `8mb-fixtures/`. Raw artifacts
are intentionally not committed.
