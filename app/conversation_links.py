"""Recognize explicit web links in rendered conversation text, without Qt or I/O.

Offsets are Python string offsets, not QTextDocument UTF-16 offsets.
Markdown parsing belongs to the renderer.
"""

from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ConversationLink:
    start: int
    end: int
    kind: str
    target: str


_MARKDOWN_LINK = re.compile(r"\[[^\]\r\n]*\]\((https?://[^\s<>]+|www\.[^\s<>]+)\)", re.IGNORECASE)
_WEB_TOKEN = re.compile(r"[^\s<>\"'`，。；！？、：【】《》（）,;]+")


def web_url(text: str) -> str | None:
    """Validate an explicit http(s) or www target without filesystem/network I/O."""
    if not text or text != text.strip() or re.search(r"\s|[<>\\\x00-\x1f]", text):
        return None
    explicit = bool(re.match(r"https?://", text, re.IGNORECASE))
    if not explicit and not text.lower().startswith("www."):
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
    if (len(ascii_host) > 253
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p)
                   for p in labels)):
        return None
    if explicit:
        return candidate
    if len(labels) < 3:
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


def recognize_links(text: str, *, cancelled=lambda: False) -> list[ConversationLink]:
    """Return explicit web links, excluding fenced code and bare domains."""
    links: list[ConversationLink] = []
    fences = fenced_ranges(text)
    # Tool details retain raw Markdown, so only its explicit web destination
    # receives an anchor. Reply Markdown anchors come from the renderer.
    occupied = list(fences)
    for markdown in _MARKDOWN_LINK.finditer(text):
        if cancelled():
            return []
        start, end = markdown.span(1)
        if any(start < right and end > left for left, right in occupied):
            continue
        url = web_url(markdown[1])
        if url:
            links.append(ConversationLink(start, end, "url", url))
            occupied.append(markdown.span())
    for token in _WEB_TOKEN.finditer(text):
        if cancelled():
            return []
        start, end = _trim(text, token.start(), token.end())
        if start >= end or any(start < right and end > left for left, right in occupied):
            continue
        url = web_url(text[start:end])
        if url:
            links.append(ConversationLink(start, end, "url", url))
    return sorted(links, key=lambda item: item.start)
