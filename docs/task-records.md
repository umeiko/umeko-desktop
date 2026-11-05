# Local task records

Open **Task records** from the Widget menu in the lower-right corner of chat.
Save the objective and scope.
From an idle chat in the same project, choose **Link next message** and send a
message. Each linked send creates an attempt. To continue or retry, select the
same task from the original chat or another chat in the project. Follow-ups
during the turn belong to the active attempt. The scope records the user's
authorization and existing Pi tool permissions continue to apply.

A local SQLite ledger stores stable task IDs, project paths, actual execution
directories, session and message identifiers, steps, and file references. Pi
JSONL holds the messages. The panel checks whether referenced session files
still carry the expected session ID. A removed message entry leaves a
historical reference that can no longer be resolved in Pi.

The ledger updates each operation in a transaction. One desktop process holds
the profile's ledger lock while using it. On the next open, an interrupted
attempt becomes **Needs recovery**. User stops and runtime exits also require
recovery. Continuing creates a fresh attempt through a user send.

Execution, submission, generation, verification and acceptance are recorded
separately. A tool can submit some files and fail to deliver others. The
attempt preserves those files and reports the delivery failure. **Check file
versions** saves a point-in-time result for the delivered files. **Accept
attempt** records the user's decision on the latest finished attempt. Earlier
attempts and their acceptance timestamps remain available across retries.

Local attachment versions are captured at send. Delivery versions are captured
when the desktop receives the Pi delivery event, including nested delivery
calls. A regular file version is a fingerprint of its resolved path, device,
file identity, size and change and modification times. A missing or moved file
is marked as such. A changed version at the same path is shown separately from
historical verification or acceptance. Directories retain a path without a
verifiable version. Remote URLs and temporary Diff snapshots are outside the
local file ledger. File bytes stay in the original filesystem.

Records are retained until deleted. Deletion cascades through the task's
attempts, steps and file references. Pi history and project files are retained.
Opening the panel reads records and checks references independently of Pi,
the active chat, and its draft and attachments.

The built-in Widget uses the scoped Widget Host API. The ledger and execution
tracking belong to the application and survive closing the Widget.
