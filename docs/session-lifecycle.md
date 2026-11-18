# Session lifecycle and JSONL import

Related issue: umeiko/umeko-desktop#133.

Archive moves a project or conversation into the archive. Restore brings it back. Legacy project-removal entries also remain discoverable in the archive.

Delete asks for confirmation, then erases app-managed transcripts, image copies, child-agent histories, derived indexes and saved chat metadata. Project deletion includes archived and unindexed managed chats for that workspace. The source project folder, source attachments and imported backup files are preserved. Running tasks or child agents must stop first. A failed cleanup keeps its sidebar entry for retry and explains the failure.

Drop Pi JSONL files onto a project row (or one of its conversations) to import there. Empty sidebar space creates ungrouped conversations. The worker validates UTF-8, supported Pi versions, record types, unique IDs and parent/reference integrity before publishing an atomic copy with a new session UUID. Filesystem parsing/deletion runs outside the GUI process. Imports never execute extensions or tools.
