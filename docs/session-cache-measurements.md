# Local session-switch measurements

Local Windows measurements with CPython 3.14.7, PySide6 6.10.2 and native Pi 1.3.0; Main.qml rendered offscreen in software at 1300 × 1000. Baseline used unchanged origin/main product code at e2445a8. Final after used integrated commit 5137d05 on perf/session-lru-cache. The integrated branch also includes #59/current-main changes and the 0.6.8 vision guard; these measurements do not isolate pure cache causality. No model call is made. These are local measurements, not CI thresholds.

Across the six cached-return cells, 6 of 6 browse medians are lower; baseline/after ratios range 1.89–3.17. Native Pi was already cached on both versions, so its cached startup cost is zero in both; this comparison does not establish a new kernel-startup saving.

Each cell has five observations. Fixtures contain exactly 10, 100 or 500 visible user/assistant messages, code blocks, Markdown tables and long native tool results in Chinese or English. The ideal internal Test provider/test-model is configured. Every measured operation is inspect rather than prompt; the provider call count remains zero. There is no real model/API request.

History + activation measures Controller.openSession until the requested target becomes active, including synchronous model projection and signals. Render measures pending history-page readiness and the first available virtual-list QML/software scenegraph frame. Live raw-text fallback may display before background rich presentation finishes; this measurement does not wait for every background highlight task. Fixed stabilization sleeps are not inserted into the measured render phase. The event loop pumps Qt and briefly releases the Python GIL while asynchronous product work finishes.

Read-only history browsing starts no Pi process. After measuring browsing, a separate explicit native inspect measures cold kernel ready and the complete inspect roundtrip. The latter includes native state/resources serialization, not inference. Controlled eviction calls the real PiSessionPool.retire lifecycle and drops the inactive SessionState to force disk history reload; automatic LRU capacity behavior is covered separately by functional tests.

All values below are medians in milliseconds, shown as **baseline → after**. Each total has its own median; sums of separately reported medians need not equal the total median.

| Language | Messages | Switch | History + activation | Render | Browse total | Kernel ready | Inspect total |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| zh | 10 | first_open | 104.7 → 98.2 | 5.3 → 22.9 | 127.8 → 121.1 | 2043.3 → 1829.6 | 2661.4 → 2296.8 |
| zh | 10 | switch_back | 796.6 → 244.5 | 9.5 → 9.1 | 806.0 → 254.2 | 0.0 → 0.0 | 600.9 → 519.4 |
| zh | 10 | evicted | 144.3 → 71.8 | 6.6 → 20.6 | 150.9 → 92.3 | 2044.5 → 1748.5 | 2713.3 → 2289.9 |
| zh | 100 | first_open | 145.2 → 139.0 | 5.6 → 21.4 | 157.0 → 194.4 | 2296.1 → 2024.7 | 2915.3 → 2648.0 |
| zh | 100 | switch_back | 804.8 → 288.4 | 226.5 → 220.3 | 1047.2 → 508.5 | 0.0 → 0.0 | 732.8 → 687.1 |
| zh | 100 | evicted | 183.3 → 132.4 | 389.1 → 385.3 | 564.6 → 538.9 | 2073.2 → 2036.8 | 2692.8 → 2587.6 |
| zh | 500 | first_open | 354.1 → 379.1 | 218.0 → 234.0 | 560.5 → 613.1 | 2196.1 → 2284.7 | 2755.6 → 3076.5 |
| zh | 500 | switch_back | 910.7 → 385.9 | 235.1 → 232.1 | 1138.6 → 602.9 | 0.0 → 0.0 | 653.8 → 557.3 |
| zh | 500 | evicted | 514.6 → 444.8 | 266.3 → 207.3 | 806.8 → 654.8 | 2084.0 → 2053.3 | 2899.0 → 2596.5 |
| en | 10 | first_open | 139.1 → 131.3 | 8.9 → 26.9 | 166.2 → 159.9 | 2604.6 → 2185.2 | 3312.2 → 2916.8 |
| en | 10 | switch_back | 935.0 → 309.2 | 6.9 → 26.1 | 941.8 → 334.3 | 0.0 → 0.0 | 721.1 → 638.8 |
| en | 10 | evicted | 163.6 → 92.5 | 13.9 → 25.4 | 191.7 → 112.1 | 2325.9 → 2065.9 | 3020.8 → 2733.3 |
| en | 100 | first_open | 132.8 → 138.7 | 6.9 → 27.1 | 148.0 → 185.4 | 2301.3 → 2161.9 | 2905.3 → 2924.9 |
| en | 100 | switch_back | 945.0 → 299.6 | 476.6 → 210.5 | 1384.4 → 510.9 | 0.0 → 0.0 | 803.3 → 777.7 |
| en | 100 | evicted | 140.7 → 93.1 | 428.9 → 418.3 | 555.5 → 511.3 | 2317.2 → 2077.1 | 3072.9 → 2741.2 |
| en | 500 | first_open | 377.0 → 376.1 | 271.8 → 190.0 | 638.8 → 554.0 | 2349.8 → 2128.7 | 3221.0 → 2859.8 |
| en | 500 | switch_back | 1114.1 → 428.5 | 284.5 → 273.7 | 1400.8 → 693.5 | 0.0 → 0.0 | 749.7 → 794.0 |
| en | 500 | evicted | 608.5 → 487.4 | 295.1 → 237.8 | 871.9 → 691.4 | 2321.8 → 2102.5 | 3071.6 → 2734.8 |

The existing virtual ListView/paged-history design is retained and finished live rows also use bounded presentation/render reuse. Cold live rows retain an immediately displayable fallback; warmed paged rows reuse prepared presentation. These measurements cover first available frame cost and support retaining the existing virtualization rather than rebuilding a second list. They do not establish that history indexing or all Qt/QML work depends only on visible area.

Final first-open render medians for 10/100/500 messages are 22.9/21.4/234.0 ms in Chinese and 26.9/27.1/190.0 ms in English. Cold disk/history work and explicit native Pi state/resource work remain separate costs.

The initial implementation and its regressions are retained as [initial diagnostic data](session-cache-measurements-after-initial.json), with its original [capacity 0](session-cache-measurements-memory-capacity0-initial.json) and [capacity 3](session-cache-measurements-memory-capacity3-initial.json) memory samples. One targeted initial cached-return profile found changed emission 500.5 ms, viewChanged 203.8 ms, chatChanged 139.3 ms, ChatModel.set_snapshot 120.1 ms, ChatModel.update 0.10 ms and store.save 1.50 ms (nested stages, not additive). This motivated suppressing global configuration notification when activation did not change configuration, while keeping view/chat notifications. The [profile JSON](session-cache-measurements-profile-cached.json) is a single diagnostic, not a benchmark median or caller-edge proof.

Memory uses two fresh offscreen Python processes with equivalent warmed sequences: visit three native sessions with 500 visible messages each (Chinese/English/Chinese), inspect each, then switch to a resource-free blank session. Capacity 0 and capacity 3 differ only in the configured session-cache capacity.

| End state after switching blank | Capacity 0 | Capacity 3 | Difference |
| --- | ---: | ---: | ---: |
| Cached native Pi processes | 0 | 3 | 3 |
| Node RSS MiB | 0.0 | 387.0 | +387.0 |
| Python + QML RSS MiB | 298.7 | 305.5 | +6.7 |

RSS is one point sample per end state. Python and QML share one process. Python allocators may retain freed pages, so this is not exact retained-object size. Empty-to-warmed deltas, individual Node RSS and intermediate samples are preserved in raw JSON; those deltas include history/index work. This is not a sustained-growth test or a measurement of physically shared pages.

First-open is application-cold per unique fixture; the operating-system disk cache is not flushed. Offscreen rendering does not establish frame-to-display latency. Timing varies with machine load. These observations establish neither model speed nor production stability.

Commands:

```text
.venv/Scripts/python.exe scripts/measure-session-switch.py --label baseline
.venv/Scripts/python.exe scripts/measure-session-switch.py --label after
.venv/Scripts/python.exe scripts/measure-session-switch.py --label memory-capacity0 --memory-only --cache-size 0
.venv/Scripts/python.exe scripts/measure-session-switch.py --label memory-capacity3 --memory-only --cache-size 3
```

Install application requirements and local-only psutil into the measurement environment. The script is intentionally outside CI. Raw observations: [baseline](session-cache-measurements-baseline.json), [after](session-cache-measurements-after.json), [capacity 0 memory](session-cache-measurements-memory-capacity0.json), [capacity 3 memory](session-cache-measurements-memory-capacity3.json).
