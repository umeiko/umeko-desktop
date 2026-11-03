"""Recognize links in already-rendered conversation text, without Qt or network I/O.

Offsets are Python string offsets, not QTextDocument's UTF-16 offsets. Filesystem
existence is checked anew on every call. Markdown parsing belongs to the renderer.
"""

from dataclasses import dataclass
import ipaddress
import ntpath
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from publicsuffixlist import PublicSuffixList


@dataclass(frozen=True)
class ConversationLink:
    start: int
    end: int
    kind: str
    target: str
    line: int | None = None
    column: int | None = None


# These links may be revealed/copied, but must never be launched by the UI.
EXECUTABLE_SUFFIXES = frozenset({
    ".exe", ".bat", ".cmd", ".ps1", ".psm1", ".psd1", ".sh", ".bash",
    ".zsh", ".fish", ".msi", ".msp", ".com", ".scr", ".pif", ".lnk",
    ".app", ".command", ".desktop", ".appimage", ".run", ".py", ".pyw",
    ".js", ".jse", ".mjs", ".cjs", ".vbs", ".vbe", ".wsf", ".wsh",
    ".jar", ".pl", ".rb", ".php", ".lua", ".hta", ".reg", ".scf",
})

# Several source extensions are real country suffixes (.py, .md, .sh, .rs).
# Bare source names must not turn into websites merely because PSL accepts them.
_FILE_SUFFIXES = (EXECUTABLE_SUFFIXES - {".com", ".app", ".run"}) | frozenset({
    ".md", ".rst", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf", ".xml", ".html", ".htm", ".css", ".scss",
    ".ts", ".tsx", ".jsx", ".vue", ".svelte", ".c", ".h", ".cpp",
    ".hpp", ".cc", ".cs", ".rs", ".go", ".java", ".kt", ".swift",
    ".sql", ".db", ".sqlite", ".pdf", ".docx", ".xlsx", ".pptx",
})

# The dependency ships this PSL snapshot; constructing it does not fetch URLs.
_PSL = PublicSuffixList(accept_unknown=False)
_LOCATION = re.compile(r":([1-9][0-9]*)(?::([1-9][0-9]*))?$")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_WINDOWS_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[/\\]|\\\\)")
_CHUNK = re.compile(r"[^\r\n<>\"'`，。；！？、：【】《》（）,;]+")
_TOKEN = re.compile(r"[^\s<>\"'`，。；！？、：【】《》（）,;]+")
_WEB_TOKEN = _TOKEN


def is_executable_path(path: str | os.PathLike) -> bool:
    """Classify runnable file types, plus executable POSIX extensionless files."""
    value = os.fspath(path)
    suffix = ntpath.splitext(value.rstrip("/\\"))[1].lower()
    if suffix in EXECUTABLE_SUFFIXES:
        return True
    return (not suffix and os.name != "nt" and os.path.isfile(value)
            and os.access(value, os.X_OK))


def web_url(text: str) -> str | None:
    """Validate a complete http(s)/www/bare-domain target using the offline PSL.

    Explicit http(s) links also permit IP addresses and localhost for local web
    tools. Bare links require a recognized, registrable public domain. Other
    schemes, credentials, whitespace and malformed ports are rejected.
    """
    if not text or text != text.strip() or re.search(r"\s|[<>\\\x00-\x1f]", text):
        return None
    explicit = bool(re.match(r"https?://", text, re.IGNORECASE))
    if not explicit and _SCHEME.match(text):
        # domain:port is allowed; an arbitrary URI scheme is not.
        if not re.match(r"[^/:]+\.[^/:]+:[0-9]+(?:[/?#]|$)", text):
            return None
    candidate = text if explicit else "https://" + text
    try:
        parsed = urlsplit(candidate)
        host = parsed.hostname
        if (parsed.scheme.lower() not in {"http", "https"} or not host
                or parsed.username is not None or parsed.password is not None):
            return None
        if parsed.port is not None and not 0 < parsed.port <= 65535:
            return None
        ascii_host = host.encode("idna").decode("ascii").lower()
    except (ValueError, UnicodeError):
        return None
    try:
        ipaddress.ip_address(ascii_host)
        return candidate if explicit else None
    except ValueError:
        pass
    if explicit and ascii_host == "localhost":
        return candidate
    labels = ascii_host.split(".")
    if (len(ascii_host) > 253 or len(labels) < 2
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p)
                   for p in labels)
            or _PSL.privatesuffix(ascii_host) is None):
        return None
    if not explicit and not ascii_host.startswith("www."):
        if "." + labels[-1] in _FILE_SUFFIXES:
            return None
    return candidate


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and (text[start].isspace() or text[start] in "([{（"):
        start += 1
    while end > start:
        last = text[end - 1]
        if last.isspace() or last in ".:!?，。；！？、）":
            end -= 1
        elif last in ")]}":
            opening = {")": "(", "]": "[", "}": "{"}[last]
            value = text[start:end]
            if value.count(last) > value.count(opening):
                end -= 1
            else:
                break
        else:
            break
    return start, end


def _resolved_path(value: str, workspace: str | os.PathLike) -> str | None:
    """Resolve only existing targets; never guess a missing absolute suffix."""
    if not value or "\x00" in value:
        return None
    # A URI must not become a local relative filename or an inner URL match.
    scheme = _SCHEME.match(value)
    if scheme and not _WINDOWS_ABSOLUTE.match(value):
        return None
    try:
        if _WINDOWS_ABSOLUTE.match(value):
            # ntpath preserves Windows absolute identity on POSIX test hosts.
            absolute = ntpath.normpath(value)
            if os.path.exists(absolute):
                return os.path.realpath(absolute) if os.name == "nt" else absolute
            return None
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = Path(workspace).expanduser() / candidate
        if candidate.exists():
            return str(candidate.resolve())
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def _path_link(text: str, start: int, end: int,
               workspace: str | os.PathLike) -> ConversationLink | None:
    start, end = _trim(text, start, end)
    value = text[start:end]
    # A real colon-bearing POSIX name wins over a diagnostic line suffix.
    resolved = _resolved_path(value, workspace)
    if resolved:
        return ConversationLink(start, end, "path", resolved)
    location = _LOCATION.search(value)
    if location:
        resolved = _resolved_path(value[:location.start()], workspace)
        if resolved:
            return ConversationLink(start, end, "path", resolved,
                                    int(location[1]), int(location[2]) if location[2] else None)
    return None


def fenced_ranges(text: str) -> list[tuple[int, int]]:
    """Find Markdown-style fenced blocks in plain tool output, including EOF."""
    ranges = []
    opening = None
    offset = 0
    for line in text.splitlines(keepends=True):
        match = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})([^\r\n]*)", line)
        if opening is None:
            if match:
                marker = match[1]
                opening = (offset, marker[0], len(marker))
        elif (match and match[1][0] == opening[1]
              and len(match[1]) >= opening[2] and not match[2].strip()):
            ranges.append((opening[0], offset + len(line)))
            opening = None
        offset += len(line)
    if opening is not None:
        ranges.append((opening[0], len(text)))
    return ranges


def recognize_links(text: str, workspace: str | os.PathLike) -> list[ConversationLink]:
    """Return non-overlapping existing-path and web links in rendered plain text.

    Quoted spans and whole fragments support spaces, as do paths beginning with
    a slash/drive/project component followed by spaced components. Unbounded
    bare filenames with spaces in prose are ambiguous; renderers should submit
    the inline-code fragment separately if they have its formatting boundary.
    """
    if not text:
        return []
    links: list[ConversationLink] = []
    occupied: list[tuple[int, int]] = fenced_ranges(text)

    def overlaps(start: int, end: int) -> bool:
        return any(start < right and end > left for left, right in occupied)

    # Whole/quoted/punctuation-bounded spans let an existing path contain spaces.
    for chunk in _CHUNK.finditer(text):
        if overlaps(chunk.start(), chunk.end()):
            continue
        whole = _path_link(text, chunk.start(), chunk.end(), workspace)
        if whole:
            links.append(whole)
            occupied.append((whole.start, whole.end))
            continue
        tokens = list(_TOKEN.finditer(text, chunk.start(), chunk.end()))
        for index, token in enumerate(tokens):
            start, end = _trim(text, token.start(), token.end())
            if overlaps(start, end):
                continue
            value = text[start:end]
            found = _path_link(text, start, end, workspace)
            # Reserve scheme/absolute tokens even when nonexistent: do not link
            # example.com inside /missing/example.com or file:///example.com.
            scheme = _SCHEME.match(value)
            is_absolute = bool(_WINDOWS_ABSOLUTE.match(value) or value.startswith(("/", "~/")))
            if found is None and scheme and not _WINDOWS_ABSOLUTE.match(value):
                url = web_url(value)
                if url:
                    links.append(ConversationLink(start, end, "url", url))
                occupied.append((start, end))
                continue
            # Spaces may occur inside an absolute or project-relative path.
            # Longest existing prefix wins; checks are confined to this chunk.
            if "/" in value or "\\" in value:
                for later in tokens[index + 1:]:
                    extended = _path_link(text, start, later.end(), workspace)
                    if extended:
                        found = extended
            if found:
                links.append(found)
                occupied.append((found.start, found.end))
            elif is_absolute:
                occupied.append((start, end))

    for token in _WEB_TOKEN.finditer(text):
        start, end = _trim(text, token.start(), token.end())
        if start >= end or overlaps(start, end):
            continue
        url = web_url(text[start:end])
        if url:
            links.append(ConversationLink(start, end, "url", url))
            occupied.append((start, end))
    return sorted(links, key=lambda item: item.start)
