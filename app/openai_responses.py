"""Bridge the agent's chat/tool history to the official Responses API."""

def text_of(content):
    return content if isinstance(content, str) else '\n'.join(p.get('text', '') for p in content or [] if p.get('type') == 'text')


def responses_request(messages, tools, max_tokens, parameters):
    items = []
    for message in messages:
        role, content = message['role'], message.get('content')
        if role == 'tool':
            items.append(dict(type='function_call_output', call_id=message['tool_call_id'], output=text_of(content)))
            continue
        if content:
            parts = content
            if isinstance(content, list):
                parts = []
                for part in content:
                    if part['type'] == 'text': parts.append(dict(type='input_text', text=part['text']))
                    elif part['type'] == 'image_url':
                        image = part['image_url']
                        parts.append(dict(type='input_image', image_url=image['url'], detail=image.get('detail', 'auto')))
                if role == 'assistant': parts = text_of(content)
            items.append(dict(role=role, content=parts))
        for call in message.get('tool_calls') or []:
            items.append(dict(type='function_call', call_id=call['id'], name=call['function']['name'], arguments=call['function']['arguments']))
    body = dict(input=items, max_output_tokens=max_tokens, stream=True, store=False)
    if tools: body['tools'] = [dict(type='function', name=t['name'], description=t.get('description', ''), parameters=t['parameters'], strict=False) for t in tools]
    for name in ('temperature', 'top_p', 'parallel_tool_calls', 'tool_choice'):
        if name in parameters: body[name] = parameters[name]
    if isinstance(body.get('tool_choice'), dict) and body['tool_choice'].get('type') == 'function':
        body['tool_choice'] = dict(type='function', name=body['tool_choice']['function']['name'])
    if parameters.get('reasoning_effort'): body['reasoning'] = dict(effort=parameters['reasoning_effort'])
    return body


def responses_events(events):
    calls, text_seen, completed = {}, False, False
    def chunk(delta=None, finish=None, usage=None):
        return dict(choices=[dict(index=0, delta=delta or {}, finish_reason=finish)], **({'usage': usage} if usage else {}))
    def tool(item):
        slot = len(calls)
        calls[item['id']] = dict(index=slot, arguments=bool(item.get('arguments')))
        return chunk(dict(tool_calls=[dict(index=slot, id=item['call_id'], type='function', function=dict(name=item['name'], arguments=item.get('arguments') or ''))]))
    for event in events:
        kind = event.get('type')
        if kind in ('error', 'response.failed'):
            raise ValueError(str(event.get('error') or event.get('response', {}).get('error') or 'Responses API failed'))
        if kind == 'response.output_text.delta' or kind == 'response.refusal.delta':
            text_seen = True
            yield chunk(dict(content=event['delta']))
        elif kind == 'response.reasoning_summary_text.delta':
            yield chunk(dict(reasoning_content=event['delta']))
        elif kind == 'response.output_item.added' and event['item']['type'] == 'function_call':
            yield tool(event['item'])
        elif kind in ('response.function_call_arguments.delta', 'response.function_call_arguments.done'):
            slot = calls.get(event['item_id'])
            if slot is None: raise ValueError('Responses tool call missing its declaration')
            arguments = event.get('delta', '') if kind.endswith('.delta') else (event.get('arguments', '') if not slot['arguments'] else '')
            if arguments:
                slot['arguments'] = True
                yield chunk(dict(tool_calls=[dict(index=slot['index'], function=dict(arguments=arguments))]))
        elif kind in ('response.completed', 'response.incomplete') or event.get('object') == 'response':
            response = event.get('response', event)
            if response.get('status') == 'failed': raise ValueError(str(response.get('error')))
            for item in response.get('output', []):
                if item['type'] == 'function_call' and item['id'] not in calls: yield tool(item)
                elif item['type'] == 'message' and not text_seen:
                    value = ''.join(p.get('text', p.get('refusal', '')) for p in item.get('content', []))
                    if value: yield chunk(dict(content=value))
            details = response.get('incomplete_details') or {}
            reason = details.get('reason')
            if response.get('status') == 'incomplete' and reason not in ('max_output_tokens', 'content_filter'):
                raise ValueError('Incomplete Responses API result: ' + str(reason))
            finish = 'length' if reason == 'max_output_tokens' else 'content_filter' if reason == 'content_filter' else 'tool_calls' if calls else 'stop'
            raw = response.get('usage') or {}
            usage = dict(prompt_tokens=raw.get('input_tokens', 0), completion_tokens=raw.get('output_tokens', 0), total_tokens=raw.get('total_tokens', 0))
            if raw.get('input_tokens_details'): usage['prompt_tokens_details'] = raw['input_tokens_details']
            if raw.get('output_tokens_details'): usage['completion_tokens_details'] = raw['output_tokens_details']
            yield chunk(finish=finish, usage=usage)
            completed = True
    if not completed: raise ValueError('Responses API stream ended before completion')
