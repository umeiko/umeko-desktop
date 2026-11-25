# Task records

Task records is disabled by default. Enable **Task records** in Widget management,
then open it from the Widget menu in the lower-right corner of chat. A saved
enable/disable choice is kept. Disabling it cancels unsent preparation; a work
record that is already running finishes normally.
Task records keeps a goal, its work history and delivered files. Work happens
in chat, and Agent requests are sent only from chat.

1. Choose **Record a goal**, enter the goal and the allowed scope, then choose
   **Save and prepare in this chat**. The scope records the user's
   instructions; Pi tool permissions follow the usual settings.
2. The pending card names the goal and target chat and says **Not started**.
   Choose **Go to chat and send**, type the actual request and send it. Existing
   drafts and attachments are kept. **Cancel** removes the preparation only.
   While a chat is busy, a goal can be saved without preparing it.
3. When work ends, the record opens **Delivered files** first. **View file** uses
   the document preview and returns to the same Widget. **Work history**
   shows a colored timeline; the right-side nodes preview and jump within the
   current page. Scrolling beyond a page edge loads the next or previous
   page. A single work record uses a timestamp/status label; multiple records use
   a selector. IDs, paths, scope and other references are folded by default.
4. **Check delivered files** shows progress, counts by result and the check time.
   It compares filesystem metadata, so it shows whether files exist and changed;
   review their content yourself. **Confirm completion…** asks the user to
   confirm they reviewed the result before saving a user-confirmation timestamp.
   The record shows execution end, file checks and user confirmation separately.

**Continue in this chat…** prepares the next manually sent message. Each new
linked send creates a new work record under the same goal. Earlier work and
confirmation timestamps stay read-only. When continuing in another chat, include
the context it needs in your message. Follow-ups during a running turn stay in
that work record. Interrupted or failed work explains the cause and offers
continuation through an idle chat in the same project. Text is sent only when you
send it in chat.

## Storage and limits

A local SQLite ledger stores stable task IDs, project paths, execution
directories, session/message references, steps and local file references. Pi
JSONL remains the source of chat messages. If a chat or message is removed, its
reference in the record can no longer be opened. The ledger is transactional and
one process holds the profile's ledger lock. Interrupted work becomes pending on
next open.

New steps and files keep their first observed timestamp. Updating a tool's
state keeps its first time and records the update separately. Schema-1 data
migrates with the timestamps it has; nodes without one are labeled
**Time not recorded**.

Partial delivery keeps successful files and records a failed result.
Versions fingerprint resolved path, device, identity, size and change/modified
times. A replacement at the same path is shown as changed, whatever earlier
checks or confirmations said. Directories keep paths only. The ledger tracks
local files; remote URLs and temporary Diff snapshots are left out. File contents
stay in the filesystem.

The built-in Widget uses a scoped, asynchronous Host API. Its read/detail pages
are bounded (12 goals/work records, 8 chronological events plus one lookahead).
Steps, files, start/end and confirmation share one timeline order across pages.
Live changes are coalesced and refresh the current page while keeping its scroll
position. File checks run outside the GUI thread, and their results are saved
when they still belong to the active Widget/chat. File preview opens files by the
stored file ID of the specified task and work record. Execution tracking
continues after the Widget is closed. Deleting a record keeps Pi history and
project files.
