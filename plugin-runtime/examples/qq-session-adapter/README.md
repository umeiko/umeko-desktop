# QQ C2C offline session adapter (first slice of #69)

This is an **offline SDK example**, not a working QQ connector and not compatibility
with the whole Tencent dsh-qqbot plugin. Importing/enabling it creates no transport,
no tasks, no account, no network connection and no credentials. Its only Widget
method is `status`. It is not bundled as an enabled built-in Widget.

## Tested seam

`Adapter(context.sessions, transport, account=..., profile=..., allowed_senders=...)`
accepts an injected `transport.send_text(target, text)`. `receive(message)` consumes
the **normalized public SDK shape**, not raw WebSocket/webhook payloads:

```json
{"kind":"c2c","senderId":"synthetic-user","messageId":"synthetic-message",
 "content":"synthetic input",
 "replyTarget":{"scope":"c2c","targetId":"synthetic-user","msgId":"synthetic-message"}}
```

Run `receive` on a dedicated background worker, not in an SDK callback/GUI thread.
The trusted caller chooses the account, fixed existing approved profile, and exact
sender allowlist. Empty allowlists deny everyone. An inbound message cannot alter
the profile, tools, directory, permissions or current desktop conversation.

The core hashes an unambiguous tuple into account namespace / C2C peer external key,
acquires the host's persistent mapping, submits a stable message request ID, waits
for **that run ID**, replies once to the captured message target, and releases the
lease. A recreated adapter can reacquire the same host mapping using a fresh handle.
No front-chat `send_message`, history fallback, stream-delta reply, automatic
approval, proactive-send fallback, or full dsh Agent loop is used.

## Limits deliberately retained

- No official SDK dependency is installed or started here. Offline tests use real
  Umeko SDK request/response helpers, a synthetic host, and in-memory transport.
  They do not establish real Pi/model, QQ account, token, gateway or delivery success.
- Only C2C plain text; groups/guild/DM, quoted elements, attachments, bot echoes,
  streaming, QR/manual binding, credential storage and remote approvals are excluded.
- Calls are serialized globally. A future transport must provide bounded queue
  admission and cancellation; this example does not spawn a thread per message.
- Dedup retains at most 256 message identities (configurable in the core). It is
  process-local, lost on restart, and oldest entries are evicted. No exactly-once
  guarantee across restarts/eviction. Ambiguous submit/send errors are not retried
  while retained. Do not substitute a random retry request ID.
- `stop()` prevents new work and suppresses results observed after stop. It waits
  for an already-entered transport send; send implementations must be bounded. It does not
  itself cancel an already-running native turn. The owner must close Context on
  shutdown; Umeko owns task cleanup (pending approvals follow host fallback policy).
- Final text is handed to the transport in one call. Live integration must enforce
  QQ size/reply-window/rate limits; this example neither silently truncates nor
  splits messages and does not claim platform acceptance for arbitrary output.
- No UI changes or installed application acceptance were performed for this seam.

## Validation

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_qq_session_adapter tests.test_plugin_sessions_sdk
PYTHONPATH=plugin-runtime python -m umeko_plugin_sdk validate plugin-runtime/examples/qq-session-adapter
```

No real account/profile setup is required. All identities, messages and host replies
in tests are synthetic; socket creation is prohibited in the new test fixture.

## Upstream contract evidence (checked 2026-11-20)

- [qqbot-nodejs 1.0.5 package](https://github.com/tencent-connect/qqbot-nodejs/blob/429a0f1b798f3b0fcef3679e207dbc0469a1df2d/package.json): ESM, Node >=20. Python Widget code cannot import it directly.
- [QQBot public ReplyTarget and QQBotInboundMessage](https://github.com/tencent-connect/qqbot-nodejs/blob/429a0f1b798f3b0fcef3679e207dbc0469a1df2d/src/QQBot.ts): scope/targetId/msgId and normalized inbound wrapper.
- [InboundMessage](https://github.com/tencent-connect/qqbot-nodejs/blob/429a0f1b798f3b0fcef3679e207dbc0469a1df2d/src/protocol/gateway/event-dispatcher.ts): kind/senderId/messageId/content.
- [dsh-qqbot package](https://github.com/tencent-connect/dsh-qqbot/blob/505b64e95f07b276a148034df9f854c78936f203/package.json) currently declares 0.5.5, qqbot-nodejs ^1.0.5 and Cordis/dsh peers.
- [dsh gateway](https://github.com/tencent-connect/dsh-qqbot/blob/505b64e95f07b276a148034df9f854c78936f203/src/gateway/bootstrap.ts) binds dsh session events, agent/approval/question services and SDK lifecycle. None of those host contracts are implemented by this sample.

A later live channel should use a separately reviewed, pinned Node transport,
preferably packaged as a standalone Widget in `umeiko/umeko-desktop-widgets`, with
an explicit host capability check and a secure credential flow. That repository,
installation, permissions and real QQ access require separate scope. Updating an
upstream version must rerun shape/lifecycle contracts; a semver range is not a
promise of perpetual compatibility. This first slice adds no host core changes.

## Reproducible next integration steps (design only; not executed)

1. Reproduce the offline commands above on the exact desktop commit. Require the
   target host to advertise `sessions.acquire`, `submit`, `wait`, and `release`
   under `sessions.manage`; application lifecycle is mandatory. Verify these on
   the actual installed host, especially C++ edition. ZIP format compatibility
   alone does not prove that edition implements the managed-session service.
2. In a disposable host profile, have the user approve an existing
   `pluginSessionProfiles["qq-session-adapter"]["qq-test"]` with an absolute
   isolated workspace, a configured desktop model alias/provider, `tools: []`,
   `permissionMode: "ask"`, and `allowApprovals: false`. Verify the host resolves
   it successfully using the existing acquire service. Do not create/change it
   from a QQ message, auto-grant tools, or reuse the active desktop conversation.
3. Implement and separately review an opt-in Node sidecar using exactly
   `@tencent-connect/qqbot-nodejs@1.0.5`, its lockfile and public exports. Connect
   its `bot.on("message", (ctx,msg) => ...)` to a bounded JSONL queue feeding this
   Python core, and map `send_text` to `bot.sendText(target,text)`. The configured
   account is supplied out-of-band by the transport owner. Validate normalized
   frames before admission; keep replies correlated with the original msgId/runId.
   Use a fake sidecar first; test framing limits, shutdown, duplicate delivery,
   backpressure and unknown send outcome. Never add dsh internal deep imports.
4. **Credential gate:** this Widget SDK does not expose a general QQ secret-store
   API in the inspected documentation. Existing Provider credentials are not QQ
   credentials and must not be repurposed. A live sidecar therefore remains
   blocked until the host/owner supplies a reviewed secure, existing credential
   facility for this specific bot (or separately approves one). Pass only the
   required AppID/AppSecret directly into the SDK constructor through that
   facility; no secrets in config.json, JSONL message frames, command-line args,
   logs, model messages, repository files, or public status. Do not invent a
   credential mechanism or enable process/network permissions in this slice.
5. Obtain specific authorization for the test bot, allowlisted test user and
   exchange contents before any `bot.start()` or outbound call. Empty allowlist
   stays deny-all. Confirm the SDK token endpoint and transport lifecycle against
   the pinned source: injecting a custom EventTransport is not an offline
   guarantee because startup also initializes tokens. Do not start it in unit tests.
6. Before the first real reply, add bounded sender/queue admission, durable inbound
   dedup/outbox reconciliation and explicit failure status. Handle QQ output size,
   reply expiration and rate limits; never silently fall back to proactive sends.
   Run an authorized single C2C exchange, then two senders, duplicate event,
   reconnect and shutdown scenarios. Record protocol acceptance separately from
   delivery confirmation. Preserve failed/uncertain outcomes; do not replay them.
7. Only after independent acceptance decide whether the installed channel belongs
   in the separate Widgets repository. No such repository write, package install,
   credential use, live configuration or release is authorized by this example.
