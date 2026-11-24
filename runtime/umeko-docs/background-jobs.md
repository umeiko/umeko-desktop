# Background jobs

Ask Umeko to start a command, continue reading its output, send input, or stop it. Bash and PowerShell return the output so far and a command session ID if still running after 10 seconds. The explicit `timeout` parameter remains a hard deadline, including after the command moves to the background.

| Action | Input | Result |
| --- | --- | --- |
| `start` | `command`, optional `cwd` and `shell` (`bash` or `powershell`) | Unique `id`, recorded PID, status, separate stdout/stderr log paths |
| `status` | `id` | `running`, `completed`, `failed`, or `killed`, plus actual exit code/signal when available |
| `read` | `id`, optional `stdoutOffset`, `stderrOffset`, `maxBytes` | New stdout/stderr and the next byte cursors |
| `write` | `id`, `input` | Writes text to the command's stdin. Include a newline to answer a line prompt. |
| `wait` | `id`, optional `timeoutMs` | Current status; `timedOut:true` if still running at the deadline |
| `kill` | `id` | Stops this session's recorded job tree and reports its exit |
| `list` | — | Jobs owned by this session |

Start with `{"action":"start","command":"your command"}`. Save the returned `id`. Read with `{"action":"read","id":"…"}`, then pass both returned offsets on the next read to avoid repeating output. Each command gets different log files, even when the command text is identical. The job list is kept in memory; log files are written to a temporary directory and are not deleted when the job exits. After an app restart, earlier jobs are no longer listed or controllable, and their log files remain on disk.

Each model-facing read returns up to 20,000 bytes per stream, with up to three additional bytes to finish a UTF-8 character. Use the returned byte offsets for the next read or open the full output files. Wait defaults to ten seconds and accepts zero to sixty seconds. A wait timeout leaves the job running.

Jobs use the configured Bash and the session shell environment. Each new session captures the exported variables from Bash and, on Windows, PowerShell. After installing tools or changing the profile, ask Umeko to call `umeko_desktop` with operation `shell.refreshEnvironment` to refresh the current session. The operation reports capture status without returning environment values.

Keep a command's worker processes in its foreground or have its shell wait for them. Umeko stops the current session's command trees when the user clicks Stop, switches sessions, or closes the app. Windows assigns the shell to a Job Object when it starts, so its descendants are tracked even after the shell exits. Input uses standard pipes. A prompt that expects a terminal screen may require the Terminal Widget.

Background starts and stdin writes follow the user's tool permission mode. Ask mode requests approval, and automatic mode applies the command rules. List, status, read, wait and stopping an owned job remain available without a new command approval.

The same process guard covers ordinary Bash and native PowerShell calls and background starts, including common execution wrappers and real command-line breaks. It blocks image-name and bulk process termination, including `taskkill /IM`, Git Bash's `//IM`, `Stop-Process -Name`, `Get-Process python | Stop-Process`, `pkill`, `killall`, name-based WMIC deletion, PID zero, negative process groups, and commands selecting multiple PIDs, because such commands can also stop Umeko or unrelated work. To stop a job, use `background_job` with the returned job ID. A shell command targeting one explicit positive PID is allowed, including ordinary output redirection; use it only for a PID you started.

The guard matches command text to catch common accidental commands. It checks the command line as written: scripts, aliases, and the owner of a PID typed directly into a shell command are outside its scope.

## Implementation sources

The runtime pins [`@alexlikevibe/pi-bg@2.3.0`](https://www.npmjs.com/package/@alexlikevibe/pi-bg/v/2.3.0), published from [`iefnaf/pi-bg`](https://github.com/iefnaf/pi-bg). The installed npm source is the version authority for these deep imports.

| Part | Source and adaptation |
| --- | --- |
| Per-session job container | Reuses `BackgroundRegistry` from the package's [`src/state.ts`](https://github.com/iefnaf/pi-bg/blob/main/src/state.ts); each manager creates a fresh instance. |
| Process launch and direct-to-file output | Adapts [`src/spawn.ts` `spawnWithFileOutput`](https://github.com/iefnaf/pi-bg/blob/main/src/spawn.ts) for separate output files and stdin pipes. Windows desktop sessions launch through the Job Object host. |
| Shell resolution | Reuses the installed Pi coding agent's `dist/utils/shell.js` `getShellConfig`, including configured shell paths. |
| Tool blocking | Uses Pi's [`permission-gate.ts`](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/examples/extensions/permission-gate.ts) `tool_call` hook and `{block:true,reason}` return contract. The matching rules are Umeko-specific and are also enforced immediately before a background launch. No confirmation dialog is added. |
| Session lifecycle hooks | Uses the lifecycle event mechanism shown by Pi's [`confirm-destructive.ts`](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/examples/extensions/confirm-destructive.ts); Umeko adds cleanup rather than its example dialogs. |
| Command sessions, initial yield and bounded output | Adapted from [Codex unified exec, rust-v0.172.0](https://github.com/openai/codex/tree/rust-v0.172.0/codex-rs/core/src/unified_exec). |

The copied/adapted pi-bg code is covered by its MIT notice below; the complete package also retains its own license in the installed dependency.

```text
MIT License

Copyright (c) 2026 patty.io
Copyright (c) 2026 alexlikevibe

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
