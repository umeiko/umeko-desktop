# Failed-history loading profile (#101)

Measured on 2026-11-05 against Python edition `a4225c7`, then the same revision
with the fix, using synthetic conversations.

## Cause

The slowdown comes from a large upstream/native error message.
`ChatModel.project()` builds the visible error activity and also kept the
entire original `errorMessage` on its output row. `display_fragments()` splits
the visible text into 24,000-character chunks and copied that original field
into every fragment. An 8,000,027-character error produced 334 fragments, each
carrying the full error string, so the index serialized and compressed
2,688,102,255 bytes of JSON for that one error (16,087,225 after the fix).
Paging then decompressed those copies again and quickly filled the 64 MiB page
cache.

The fix consumes `errorMessage` when projecting a **copy** of the native row.
The full visible error text, partial reply and diagnostic ID stay available, and
the original JSONL and in-memory native messages are untouched. Index schema 7
rebuilds schema 6 caches, so previously inflated display rows are replaced too.

## Timings

Windows 11, CPython 3.12.14, PySide6/Qt 6.10.2, 1300×1000 offscreen software
rendering. Each fixture has 3,000 turns (6,000 user/assistant messages) plus
600 tool-call/tool-result pairs. The large-error fixture replaces the last reply
with an 8 MB error; normal and short-failure histories are controls. The same
source files were used before and after.

Each value is the median of three fresh-process runs with profiling disabled.
Cold open means a freshly built derived index. Completion is measured when the
visible message bodies are laid out and a Qt frame is captured.

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
Normal and short-failure histories stay at about the same speed. The page-cache
weight is the Python object-weight accounting used by the cache. Four display
rows were prepared at the large-error viewport.

## Profile

A single-threaded cProfile run of the index isolates the hot path:

| Operation | Before | After |
| --- | ---: | ---: |
| `TranscriptRepository.open` | 13.717 s | 0.927 s |
| JSON serialization (`json.dumps`, cumulative) | 8.710 s | 0.108 s |
| `zlib.compress` | 3.134 s | 0.090 s |

Both profiles use the same 12,825,983-byte source file, SHA-256
`167a0f248997e382da081e7f649084162b48ab0383fb5869bfe0c31248efc364`.
Exploratory profiles also covered partial replies, retry/context edits, 26 KB
error bodies and 600/3,000-turn histories. Short ordinary failures load at
normal speed; if a report involves only short errors, profile it separately.

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
row counts, cache weight and GUI timer gaps. Profiled runs also write `.prof`
files and cumulative-time text summaries. GUI runs write viewport PNGs.
Results stay in the local `artifacts/issue-101/` directory.

## Regression tests

Two regression tests cover the fix: a 280 KB error, which expanded to 3.92 MB
of serialized fragments before the fix, now stays bounded. They also check the
complete reconstructed error text, unchanged source bytes and the rebuild of a
seeded schema 6 cache.
