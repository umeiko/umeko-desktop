# Session switching measurements

Run [the local script](../scripts/measure-session-switch.py) after the normal
development setup, with the installed Pi SDK in `runtime/node_modules`:

```text
.venv/Scripts/python.exe scripts/measure-session-switch.py --mode switches --label local --observations 9 --profile-phases
.venv/Scripts/python.exe scripts/measure-session-switch.py --mode sequence --label local-sequence --profile-phases
.venv/Scripts/python.exe scripts/measure-session-switch.py --mode memory --label local-memory --visits 8 --profile-phases
```

The script uses Qt offscreen/software, temporary saved sessions and an ideal
Test provider / test-model. It makes no model/API requests, closes its Pi
processes and removes fixtures. `--profile-phases` instruments a temporary QML
copy. JSON stays in local `artifacts/session-switch-measurements/`; override
with `--output-dir`. Use the same script and environment with each source
revision to compare them. Raw results are not committed.

Windows, CPython 3.14.7, Qt 6.10.2, Pi 1.3.0, 1300×1000 software frames.
Main `73cba53` versus final implementation `61a7f5b`; milliseconds,
median [interquartile range]. Fixtures include code, tables and tool output.

| Flow | Samples | Main | Final |
| --- | ---: | ---: | ---: |
| Used medium session, recency rank 2/3 | 10 | 1141 [139] | 339 [29] |
| Used medium session, recency rank 4/5 | 10 | 1066 [111] | 345 [27] |
| Five medium sessions, five complete cycles | 25 | 1059 [147] | 344 [32] |
| First open, Chinese 10 messages | 9 | 168 [32] | 149 [34] |
| First open, English 10 messages | 9 | 148 [37] | 128 [40] |
| First open, Chinese 100 messages | 9 | 179 [34] | 146 [82] |
| First open, English 100 messages | 9 | 162 [23] | 156 [51] |
| First open, Chinese 500 messages | 9 | 712 [42] | 767 [267] |
| First open, English 500 messages | 9 | 730 [43] | 722 [107] |

The sequence warms A–E, returns to A, then runs B/C/D/E/A five times:
every revisit is rank 5. Separate subsequent probes select ranks 2/3/4/5
five times each. Native initialization is outside timed switches; browsing
does not start Pi. First open is application-cold, not OS-cache-cold.

After eight native 500-message sessions then blank, Pi count is 8→3,
summed Pi RSS 846.8→369.6 MiB and Python/QML RSS 348.3→322.0 MiB.
This is about 504 MiB less total RSS, a point sample rather than unique
physical memory or sustained-growth evidence.

The discarded render-cache trial (`28b4644`, nine samples per fixture) met
the ≥20% render improvement threshold in only 2/6 fixtures, short of 4/6;
its first-open browse medians rose 27–86 ms. Main rendering is restored.
Direct JavaScript Markdown probes typically took 0–0.14 ms; larger Qt event
work combines delegate creation, internal text conversion and layout.
Frame capture also includes deferred Qt work, so neither phase is pure CPU
time for a single operation.

Results vary: the final read-only English 100-message cached return was
116 [299]→362 [389] ms, with strongly bimodal samples. Chinese long first
open also had a higher median and wide spread. These measurements do not
establish universal speedup, display latency or long-term stability; the
first frame may precede background formatting. No larger view-retention
mechanism was added.
