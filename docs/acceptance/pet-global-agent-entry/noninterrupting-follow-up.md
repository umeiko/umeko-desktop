# Noninterrupting follow-up from the desktop pet (#152)

Base: PR #190 at `9733be934c4d4f906b4247e165190ea586f1503d`. The increment selects an existing global-agent conversation, binds the preview to the current native run, and queues a follow-up without interrupting it. Replaced or ended runs are not silently used, and an uncertain outcome does not replay. A queue receipt is not completion.

## Acceptance evidence

The screenshots show the actual Linux Qt offscreen UI with isolated Chinese test data and both UI languages. Pi 1.5.2 was verified against the tested bridge; a deterministic local fixture held the initial model response until the follow-up was acknowledged. No external model or user account was used.

| UI | Preview | Queue receipt |
|---|---|---|
| Chinese | [Preview](follow-up-preview-zh.png) | [Queued](follow-up-queued-zh.png) |
| English | [Preview](follow-up-preview-en.png) | [Queued](follow-up-queued-en.png) |

Checks passed: 62 focused Python tests, 5 Node queue tests, verified Pi runtime, and actual Qt/Pi acceptance in both languages.

## Limits

No persistent pet draft, session-local child-agent delegation, end-to-end completion mapping, or Windows native/IME acceptance. If the exact receipt is lost, selection may remain locked until the turn ends; the draft is retained and there is no automatic retry. Replies, approvals, and Stop remain in the original Desktop conversation.
