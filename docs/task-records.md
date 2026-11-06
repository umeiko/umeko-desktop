# Task records

Task records is disabled by default. Enable **Task records** in Widget management,
then open it from the Widget menu in the lower-right corner of chat. An explicit
saved enable/disable choice is preserved. Disabling it cancels unsent preparation;
an already running work record can still finish normally.
This is a record of a goal, its work history and delivered files. Work happens
in chat; opening or browsing records never starts an Agent request.

1. Choose **Record a goal**, enter the goal and the allowed scope, then choose
   **Save and prepare in this chat**. The scope is a record of the user's
   instructions; it does not grant permissions or change Pi tool permissions.
2. The pending card names the goal and target chat and says **Not started**.
   Choose **Go to chat and send**, type the actual request and send it. Existing
   drafts and attachments are retained. **Cancel** removes preparation only.
   While a chat is busy, a goal can be saved without preparing it.
3. When work ends, the record opens **Delivered files** first. **View file** uses
   the existing document preview and returns to the same Widget. **Work history**
   shows a colored timeline; the right-side nodes preview and jump within the
   current bounded page. Scrolling beyond a page edge loads the next or previous
   page. A single work record uses a timestamp/status label; multiple records use
   a selector. IDs, paths, scope and other references are folded by default.
4. **Check delivered files** shows progress, counts by result and the check time.
   It compares filesystem metadata, not content correctness. **Confirm
   completion…** asks the user to confirm they reviewed the result before saving
   a user-confirmation timestamp. Execution ending, a file being unchanged and a
   user confirming completion are separate facts.

**Continue in this chat…** prepares the next manually sent message. Each new
linked send creates a new work record under the same goal. Earlier work and
confirmation timestamps remain read-only. Continuing in another chat does not
copy its predecessor's conversation; the user should include the needed context.
Follow-ups during a running turn stay in that work record. Interrupted or failed
work explains the cause and offers continuation through an idle chat in the same
project. Opening, canceling preparation, and returning to chat do not send text.

## Storage and limits

A local SQLite ledger stores stable task IDs, project paths, execution
directories, session/message references, steps and local file references. Pi
JSONL remains the source of chat messages. Removing a chat/message may leave an
unresolvable historical reference. The ledger is transactional and one process
holds the profile's ledger lock. Interrupted work becomes pending on next open.

New steps and files retain their first observed timestamp. Updating a tool's
state preserves its first time and records the update separately. Schema-1 data
migrates without inventing historical timestamps; undated nodes are labeled
**Time not recorded**.

Partial delivery preserves successful files and records a failed result.
Versions fingerprint resolved path, device, identity, size and change/modified
times. Replacement at the same path is shown as changed, independently of past
checks or confirmation. Directories retain paths only. Remote URLs and temporary
Diff snapshots are outside the ledger. File contents remain in the filesystem.

The built-in Widget uses a scoped, asynchronous Host API. Its read/detail pages
remain bounded (12 goals/work records, 8 chronological events plus one lookahead); it does
not accumulate every previous page. Steps, files, start/end and confirmation share
one timeline order across pages. Live changes are coalesced and refresh the current
page without returning its scroll position to the beginning. File checks run outside the GUI thread and
must still belong to the active Widget/chat before their results are persisted.
File preview accepts a stored file ID belonging to the specified task and work
record, not an arbitrary requested path. Execution tracking survives closing the
Widget. Deleting a record preserves Pi history and project files.
