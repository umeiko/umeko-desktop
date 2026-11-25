"""Measure one streamed reasoning probe without retaining its reasoning text."""
import re


def observe_reasoning(events, answer_correct):
    content, reasoning = [], []
    reasoning_tokens = None
    finish_reason = None
    for event in events:
        if event.get('error'):
            raise ValueError(str(event['error']))
        usage = event.get('usage') or {}
        details = usage.get('completion_tokens_details') or {}
        count = details.get('reasoning_tokens')
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            # Stream usage messages are cumulative snapshots.
            reasoning_tokens = max(reasoning_tokens or 0, count)
        for choice in event.get('choices', []):
            if choice.get('finish_reason') is not None:
                finish_reason = choice['finish_reason']
            delta = choice.get('delta', choice.get('message', {}))
            for key in ('reasoning_content', 'reasoning', 'reasoning_text'):
                value = delta.get(key)
                if isinstance(value, str):
                    reasoning.append(value)
                    break  # Aliases can contain the same text.
            value = delta.get('content')
            if isinstance(value, str):
                content.append(value)
            elif isinstance(value, list):
                content.extend(part.get('text', '') for part in value
                               if isinstance(part, dict) and isinstance(part.get('text'), str))
    text = ''.join(content)
    tagged = re.findall(r'<think>(.*?)(?:</think>|$)', text, flags=re.I | re.S)
    ordinary = re.sub(r'<think>.*?(?:</think>|$)', '', text, flags=re.I | re.S).strip()
    chars = len(''.join(reasoning).strip()) + sum(len(part.strip()) for part in tagged)
    return {'thinking': bool(chars or reasoning_tokens), 'content': bool(ordinary),
            'thinkingChars': chars, 'reasoningTokens': reasoning_tokens,
            'answer': ordinary, 'correct': answer_correct(ordinary),
            'finishReason': finish_reason}
