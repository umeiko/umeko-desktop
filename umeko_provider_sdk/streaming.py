"""Shared wire parsing and canonical OpenAI response events for hosts/plugins."""
from __future__ import annotations

import codecs
import json

from .errors import format_http_error


def tool_arguments(value):
    """Keep streamed JSON fragments; encode complete structured arguments once."""
    if value is None:
        return ''
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def normalize_usage(value):
    if not isinstance(value, dict):
        return {}
    aliases = {'input_tokens': 'prompt_tokens', 'output_tokens': 'completion_tokens',
               'input_tokens_details': 'prompt_tokens_details', 'output_tokens_details': 'completion_tokens_details'}
    result = {aliases.get(key, key): item for key, item in value.items() if item is not None}
    if 'total_tokens' not in result and all(isinstance(result.get(key), (int, float)) for key in ('prompt_tokens', 'completion_tokens')):
        result['total_tokens'] = result['prompt_tokens'] + result['completion_tokens']
    return result


def finish_reason(value):
    if not value:
        return None
    return {'tool_use': 'tool_calls', 'function_call': 'tool_calls',
            'max_tokens': 'length', 'max_output_tokens': 'length', 'max_completion_tokens': 'length',
            'end_turn': 'stop', 'stop_sequence': 'stop', 'completed': 'stop', 'complete': 'stop'}.get(value, value)


def upstream_error(event):
    error = event.get('error')
    if error is None and event.get('type') == 'response.failed':
        error = (event.get('response') or {}).get('error') or {'message': 'Response failed'}
    if error is None and event.get('type') == 'error':
        error = event
    if error is None:
        return None
    return ValueError(format_http_error(200, {'error': error}))


def iter_sse(chunks):
    """Read fragmented UTF-8 SSE, comments and CRLF, including final unframed data."""
    decoder = codecs.getincrementaldecoder('utf-8')()
    buffer, lines, event_name = '', [], ''
    def payload(value, name):
        event = json.loads(value)
        if name and name != 'message' and isinstance(event, dict):
            event.setdefault('type', name)
        return event
    for chunk in chunks:
        if not chunk:
            continue
        buffer += decoder.decode(chunk) if isinstance(chunk, bytes) else chunk
        while '\n' in buffer:
            line, buffer = buffer.split('\n', 1)
            line = line.rstrip('\r')
            if not line:
                if lines:
                    value, lines = '\n'.join(lines), []
                    if value.strip() == '[DONE]':
                        return
                    if value.strip():
                        yield payload(value, event_name)
                event_name = ''
            elif line.startswith('data:'):
                lines.append(line[5:].lstrip(' '))
            elif line.startswith('event:'):
                event_name = line[6:].strip()
    buffer += decoder.decode(b'', final=True)
    if buffer.startswith('data:'):
        lines.append(buffer[5:].strip())
    value = '\n'.join(lines)
    if value.strip() and value.strip() != '[DONE]':
        yield payload(value, event_name)


def response_events(response):
    content_type = response.headers.get('Content-Type', '').lower()
    if 'event-stream' not in content_type:
        raw = response.read(16 * 1024 * 1024)
        if raw.lstrip().startswith((b'{', b'[')):
            yield json.loads(raw)
        else:
            yield from iter_sse([raw])
        return
    def chunks():
        read = getattr(response, 'read1', response.read)
        while part := read(8192):
            yield part
    yield from iter_sse(chunks())


class _Thinking:
    def __init__(self):
        self.buffer = ''
        self.thinking = False

    def feed(self, value, final=False):
        self.buffer += value
        text, reasoning = [], []
        while self.buffer:
            tag = '</think>' if self.thinking else '<think>'
            position = self.buffer.find(tag)
            target = reasoning if self.thinking else text
            if position >= 0:
                target.append(self.buffer[:position])
                self.buffer = self.buffer[position + len(tag):]
                self.thinking = not self.thinking
                continue
            keep = 0
            if not final:
                for length in range(1, min(len(tag), len(self.buffer) + 1)):
                    if self.buffer.endswith(tag[:length]):
                        keep = length
            target.append(self.buffer[:-keep] if keep else self.buffer)
            self.buffer = self.buffer[-keep:] if keep else ''
            break
        return ''.join(text), ''.join(reasoning)


def normalize_openai_events(events):
    """Yield canonical chat chunks, retaining incremental text/tool delivery.

    Missing tool indexes resolve by stable id, position for a multi-call delta,
    or the last declared tool for a single continuation. Completion requires a
    finish, a non-stream message, or a usage-only tail after actual output (the
    plugin SDK also permits this tail). [DONE] alone cannot make an empty/broken
    response successful. Reapplying this adapter preserves canonical chunks.
    """
    thoughts, tools, ids, last_tool = {}, {}, {}, {}
    completed, has_output = False, False
    for event in events:
        if not isinstance(event, dict):
            raise ValueError('Invalid upstream completion event')
        error = upstream_error(event)
        if error:
            raise error
        output = {key: value for key, value in event.items() if key not in ('choices', 'usage')}
        choices = []
        for ordinal, choice in enumerate(event.get('choices') or []):
            index = choice.get('index', ordinal)
            full = choice.get('message') is not None
            raw = choice.get('message') if full else choice.get('delta')
            raw = raw or {}
            delta = {key: value for key, value in raw.items() if key not in ('content', 'reasoning', 'reasoning_text', 'reasoning_content', 'tool_calls', 'function_call')}
            reason = raw.get('reasoning_content') or raw.get('reasoning') or raw.get('reasoning_text') or ''
            finish = finish_reason(choice.get('finish_reason') or choice.get('stop_reason'))
            parser = thoughts.setdefault(index, _Thinking())
            text, tagged = parser.feed(raw.get('content') or '', final=bool(full or finish))
            if text or (full and raw.get('content') is not None):
                delta['content'] = text
            if reason or tagged:
                delta['reasoning_content'] = reason + tagged
            raw_calls = raw.get('tool_calls') or []
            if raw.get('function_call'):
                raw_calls = [dict(function=raw['function_call'])]
            normalized_calls = []
            slots = tools.setdefault(index, set())
            known_ids = ids.setdefault(index, {})
            for position, call in enumerate(raw_calls):
                tool_index = call.get('index')
                call_id = call.get('id')
                if tool_index is None:
                    if call_id in known_ids:
                        tool_index = known_ids[call_id]
                    elif call_id:
                        tool_index = max(slots, default=-1) + 1
                    elif len(raw_calls) > 1:
                        tool_index = position
                    else:
                        tool_index = last_tool.get(index, 0)
                slots.add(tool_index)
                last_tool[index] = tool_index
                if call_id:
                    known_ids[call_id] = tool_index
                function = call.get('function') or {}
                normalized = {**call, 'index': tool_index, 'function': dict(function)}
                if 'arguments' in function:
                    normalized['function']['arguments'] = tool_arguments(function['arguments'])
                normalized_calls.append(normalized)
            if normalized_calls:
                delta['tool_calls'] = normalized_calls
            if text or reason or tagged or normalized_calls:
                has_output = True
            if full and not finish:
                finish = 'tool_calls' if normalized_calls else 'stop'
            if finish:
                completed = True
            choices.append({**choice, 'index': index, ('message' if full else 'delta'): delta, 'finish_reason': finish})
        output['choices'] = choices
        if 'usage' in event:
            output['usage'] = normalize_usage(event['usage'])
            if output['usage'] and not choices and has_output:
                if not completed:
                    tail = {}
                    if 0 in thoughts:
                        text, reason = thoughts[0].feed('', final=True)
                        if text:
                            tail['content'] = text
                        if reason:
                            tail['reasoning_content'] = reason
                    output['choices'] = [dict(index=0, delta=tail, finish_reason='tool_calls' if tools.get(0) else 'stop')]
                completed = True
        if choices or output.get('usage'):
            yield output
    if not completed:
        raise ValueError('Upstream stream ended before completion')


def collect_openai(events):
    text, reasoning, calls, usage, finish, model = [], [], {}, {}, 'stop', ''
    for event in normalize_openai_events(events):
        model = event.get('model') or model
        usage.update(event.get('usage') or {})
        for choice in event.get('choices') or []:
            if choice.get('index', 0) != 0:
                continue
            delta = choice.get('delta') or choice.get('message') or {}
            if delta.get('content'):
                text.append(delta['content'])
            if delta.get('reasoning_content'):
                reasoning.append(delta['reasoning_content'])
            for call in delta.get('tool_calls') or []:
                slot = calls.setdefault(call['index'], dict(id='', type='function', function=dict(name='', arguments='')))
                if call.get('id') and call['id'] != slot['id']:
                    slot['id'] += call['id']
                function = call.get('function') or {}
                for key in ('name', 'arguments'):
                    slot['function'][key] += function.get(key) or ''
            finish = choice.get('finish_reason') or finish
    message = dict(role='assistant', content=''.join(text))
    if reasoning:
        message['reasoning_content'] = ''.join(reasoning)
    if calls:
        message['tool_calls'] = [calls[index] for index in sorted(calls)]
    return dict(object='chat.completion', model=model, choices=[dict(index=0, message=message, finish_reason=finish)], usage=normalize_usage(usage))
