# Background jobs

Ask Umeko to start a command in the background, read its output, wait for it, or stop it. The `background_job` tool keeps the conversation available while the command runs. No extra slash command or panel is required.

| Action | Input | Result |
| --- | --- | --- |
| `start` | `command`, optional `cwd` | Unique `id`, recorded PID, status, separate stdout/stderr log paths |
| `status` | `id` | `running`, `completed`, `failed`, or `killed`, plus actual exit code/signal when available |
| `read` | `id`, optional `stdoutOffset`, `stderrOffset`, `maxBytes` | New stdout/stderr and the next byte cursors |
| `wait` | `id`, optional `timeoutMs` | Current status; `timedOut:true` if still running at the deadline |
| `kill` | `id` | Stops this session's recorded job tree and reports its exit |
| `list` | — | Jobs owned by this session |

Start with `{"action":"start","command":"your command"}`. Save the returned `id`. Read with `{"action":"read","id":"…"}`, then pass both returned offsets on the next read to avoid repeating output. Each command gets different log files, even when the command text is identical. Logs remain in the session's temporary directory after the job exits; they are not restored as live jobs after an app restart.

Reads default to 64 KiB per stream; the maximum is 1 MiB per stream. A multibyte UTF-8 character can exceed a requested page size by up to three bytes so that even a one-byte page can advance. Wait defaults to ten seconds and accepts zero to sixty seconds. A wait timeout leaves the job running. Use another wait/read, or stop it by job ID.

Jobs use the existing Bash shell configuration and inherit the app's environment. Keep a command's worker processes in its foreground, or have its shell wait for them. A command that deliberately detaches descendants and exits has ended as far as the job tool is concerned. Switching/creating a session or closing a session stops that manager's running jobs. Each main or child session has its own manager; cleanup does not stop another manager's jobs. On Windows the process and its termination helper launch without a visible console window, and termination uses only `taskkill /PID <recorded PID> /T /F`.

The same pre-execution guard covers ordinary Bash calls and background starts. It blocks image-name and bulk process termination, including `taskkill /IM`, Git Bash's `//IM`, `Stop-Process -Name`, `Get-Process python | Stop-Process`, `pkill`, `killall`, name-based WMIC deletion, PID zero, negative process groups, and commands selecting multiple PIDs. Such commands can also stop Umeko or unrelated work. Prefer `background_job` with the returned job ID. A shell command targeting one explicit positive PID remains allowed, including ordinary output redirection; the caller remains responsible for starting/owning that PID.

This is a lexical guard against common accidental commands. It is not a security sandbox and does not inspect arbitrary scripts, resolve aliases, or prove ownership of a PID written directly in a shell command.

## Implementation sources

The runtime pins [`@alexlikevibe/pi-bg@2.3.0`](https://www.npmjs.com/package/@alexlikevibe/pi-bg/v/2.3.0), published from [`iefnaf/pi-bg`](https://github.com/iefnaf/pi-bg). The installed npm source is the version authority for these deep imports.

| Part | Source and adaptation |
| --- | --- |
| Per-session job container | Reuses `BackgroundRegistry` from the package's [`src/state.ts`](https://github.com/iefnaf/pi-bg/blob/main/src/state.ts); each manager creates a fresh instance. |
| Unix process launch and direct-to-file output | Reuses [`src/spawn.ts` `spawnWithFileOutput`](https://github.com/iefnaf/pi-bg/blob/main/src/spawn.ts) via the existing jiti loader. The package's default extension entry is not loaded. |
| Windows process launch | Adapts that same file-descriptor spawn pattern locally to set `windowsHide:true`; preserves separate stdout/stderr, detached launch, exit/error listeners, and descriptor cleanup. |
| Shell resolution | Reuses the installed Pi coding agent's `dist/utils/shell.js` `getShellConfig`, including configured shell paths. |
| Tool blocking | Uses Pi's [`permission-gate.ts`](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/examples/extensions/permission-gate.ts) `tool_call` hook and `{block:true,reason}` return contract. The matching rules are Umeko-specific and are also enforced immediately before a background launch. No confirmation dialog is added. |
| Session lifecycle hooks | Uses the lifecycle event mechanism shown by Pi's [`confirm-destructive.ts`](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/examples/extensions/confirm-destructive.ts); Umeko adds cleanup rather than its example dialogs. |
| Job IDs, separate log paths, byte cursors, bounded wait, owned-PID Windows tree kill, tool schema | Umeko adapter in `runtime/background-jobs.mjs`; process-command rules in `runtime/process-guard.mjs`. |

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
