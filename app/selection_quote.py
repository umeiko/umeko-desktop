"""Turn a selected passage into a Markdown quote for the chat composer."""
QUOTE_MAX_CHARS = 16000


class QuoteTooLong(ValueError):
    pass


def quote_block(text):
    if not isinstance(text, str):
        return ''
    normalized = (text.replace('\r\n', '\n').replace('\r', '\n')
                  .replace('\u2028', '\n').replace('\u2029', '\n'))
    normalized = normalized.strip('\n').rstrip()
    if not normalized.strip():
        return ''
    return '\n'.join('>' if not line.strip() else '> ' + line for line in normalized.split('\n'))


def append_quote(draft, text):
    block = quote_block(text)
    if not block:
        return draft
    if len(block) > QUOTE_MAX_CHARS:
        raise QuoteTooLong('所选内容过长，请改用“附加到聊天”')
    base = draft.rstrip() if isinstance(draft, str) else ''
    return (base + '\n\n' if base else '') + block + '\n\n'
