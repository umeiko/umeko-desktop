# Session switching measurements

Run [the local script](../scripts/measure-session-switch.py) after the normal
development setup, with the installed Pi SDK in `runtime/node_modules`:

```text
.venv/Scripts/python.exe scripts/measure-session-switch.py --mode switches --label local --observations 9 --profile-phases
.venv/Scripts/python.exe scripts/measure-session-switch.py --mode sequence --label local-sequence --profile-phases
.venv/Scripts/python.exe scripts/measure-session-switch.py --mode memory --label local-memory --visits 8 --profile-phases
```

The script uses Qt offscreen/software, temporary saved sessions and an ideal
local test provider, so it runs without model/API requests. It closes its Pi
processes and removes fixtures when done. `--profile-phases` instruments a
temporary QML copy. JSON results go to local
`artifacts/session-switch-measurements/`; change this with `--output-dir`. To
compare revisions, run the same script in the same environment on each one.

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
five times each. Native initialization happens outside the timed switches, and
browsing history starts no Pi process. First open means the application has not
loaded the session yet (the OS file cache may be warm).

After visiting eight native 500-message sessions and then a blank one, the Pi
process count went from 8 to 3, summed Pi RSS from 846.8 to 369.6 MiB and
Python/QML RSS from 348.3 to 322.0 MiB: about 504 MiB less total RSS in that
sample.

A render-cache variant (`28b4644`, nine samples per fixture) improved rendering
by 20% or more in 2 of 6 fixtures and slowed first-open browsing by 27–86 ms, so
the existing rendering path was kept. Direct JavaScript Markdown calls took
0–0.14 ms; the larger Qt event time is delegate creation, internal text
conversion and layout. Frame capture includes deferred Qt work.

The English 100-message read-only cached return moved from 116 [299] to
362 [389] ms with strongly bimodal samples, and the Chinese 500-message first
open had a higher median with a wide spread. The first frame can appear before
background formatting finishes.
