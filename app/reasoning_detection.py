"""Reasoning effort configuration, explicit metadata, and bounded API discovery.

There are no model-name guesses here. Probe results describe values accepted by
an API; accepting the deliberately invalid value warns that the API may ignore
the parameter. A caller supplies the small request and preserves its old cache
if discovery fails for reasons unrelated to effort validation.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping

from .thinking_formats import format_parameters, valid_format


EFFORT_CANDIDATES = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
OPENROUTER_EFFORTS = EFFORT_CANDIDATES[:-1]
_RANK = {value: index for index, value in enumerate(EFFORT_CANDIDATES)}
_RANK["ultra"] = _RANK["max"]  # DeepSeek's documented alias.
_INVALID_EFFORT = "__umeko_invalid_effort__"
_EFFORT = re.compile(r"\beffort\b|reasoning[_. -]*effort", re.I)
_REJECTION = re.compile(
    r"invalid|unsupported|not supported|unknown|unrecognized|unexpected|not permitted|"
    r"not allowed|must be|should be|permitted|allowed|expected|extra.forbidden|enum", re.I)
_UNRELATED = re.compile(
    r"unauthori[sz]ed|forbidden|invalid.api.key|authentication|rate.limit|too many requests|"
    r"timed?\s*out|timeout|connection|network|quota|insufficient.{0,12}(?:credit|balance)|"
    r"max[_ ](?:output[_ ]|completion[_ ])?tokens|maximum.{0,15}tokens|context.length", re.I)


def normalize_levels(raw: object) -> list[str]:
    """Validate a configured ordered list; 'off' is a separate UI action."""
    if not isinstance(raw, list):
        raise ValueError("推理等级必须为字符串列表")
    result = []
    for value in raw:
        if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("推理等级必须为非空字符串")
        value = value.strip()
        if value != "off" and value not in result:
            result.append(value)
    return result


def _canonical_levels(raw: object) -> list[str]:
    levels = normalize_levels(raw)
    return sorted(levels, key=lambda value: _RANK.get(value, len(_RANK)))


def metadata_levels(row: object) -> list[str] | None:
    """Read only documented server fields and the explicit plugin host contract.

    None means no usable declaration, whereas [] explicitly declares no levels.
    Malformed optional remote metadata is ignored rather than guessing support.
    """
    if not isinstance(row, Mapping):
        return None
    if "reasoningLevels" in row:
        try:
            return _canonical_levels(row["reasoningLevels"])
        except ValueError:
            return None
    capabilities = row.get("capabilities")
    effort = capabilities.get("effort") if isinstance(capabilities, Mapping) else None
    if isinstance(effort, Mapping):
        if effort.get("supported") is False:
            return []
        declared = [value for value in ("low", "medium", "high", "xhigh", "max")
                    if isinstance(effort.get(value), Mapping)
                    and isinstance(effort[value].get("supported"), bool)]
        if declared:
            return [value for value in declared if effort[value].get("supported") is True]
    effort = row.get("effort")
    if isinstance(effort, Mapping):
        if isinstance(effort.get("supported_levels"), list):
            try:
                return _canonical_levels(effort["supported_levels"])
            except ValueError:
                return None
    reasoning = row.get("reasoning")
    if isinstance(reasoning, Mapping) and "supported_efforts" in reasoning:
        values = reasoning["supported_efforts"]
        if values is None:
            return list(OPENROUTER_EFFORTS)
        try:
            return _canonical_levels(values)
        except ValueError:
            return None
    return None


def _error_text(error: object) -> str:
    if isinstance(error, (Mapping, list)):
        return json.dumps(error, ensure_ascii=False, default=str)
    return str(error)


def is_effort_rejection(error: object) -> bool:
    """Distinguish effort validation from auth, transport, and token-cap failures."""
    status = getattr(error, "status_code", None)
    if status in (401, 403, 408, 429) or (isinstance(status, int) and status >= 500):
        return False
    text = _error_text(error)
    return bool(_EFFORT.search(text) and _REJECTION.search(text) and not _UNRELATED.search(text))


def _field_is_effort(value: object) -> bool:
    if isinstance(value, (list, tuple)):
        return any(_field_is_effort(part) for part in value)
    return isinstance(value, str) and bool(_EFFORT.search(value))


def _structured_allowed(value: object, effort_context: bool = False) -> list[str] | None:
    if isinstance(value, Mapping):
        context = effort_context or any(_field_is_effort(value.get(key))
                                       for key in ("param", "parameter", "field", "loc", "path"))
        for key in ("allowed", "allowed_values", "enum", "permitted", "expected"):
            candidate = value.get(key)
            if context and isinstance(candidate, list):
                try:
                    return _canonical_levels(candidate)
                except ValueError:
                    pass
        for key, child in value.items():
            found = _structured_allowed(child, context or _field_is_effort(key))
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _structured_allowed(child, effort_context)
            if found is not None:
                return found
    return None


def _validation_messages(value: object) -> list[str]:
    if isinstance(value, Mapping):
        scopes = [value[key] for key in ("param", "parameter", "field", "loc", "path") if key in value]
        messages = []
        effort_scoped = any(_field_is_effort(scope) for scope in scopes)
        if not scopes or effort_scoped:
            messages.extend(("reasoning_effort: " if effort_scoped else "") + value[key]
                            for key in ("message", "msg", "detail")
                            if isinstance(value.get(key), str))
        for child in value.values():
            if isinstance(child, (Mapping, list)):
                messages.extend(_validation_messages(child))
        return messages
    if isinstance(value, list):
        return [message for child in value for message in _validation_messages(child)]
    return []


def allowed_levels(error: object) -> list[str] | None:
    """Extract an explicit effort enum, never a generic list elsewhere in an error."""
    if not is_effort_rejection(error):
        return None
    structured = error
    text = _error_text(error)
    if not isinstance(error, (Mapping, list)):
        try:
            structured = json.loads(text)
        except (ValueError, TypeError):
            structured = None
    found = _structured_allowed(structured)
    if found is not None:
        return found
    if isinstance(structured, (Mapping, list)):
        text = "\n".join(_validation_messages(structured))
    # Common OpenAI-compatible and Python/Pydantic enum validation messages.
    # Only inspect an alternatives clause near the explicitly named parameter.
    for mention in _EFFORT.finditer(text):
        clause = text[max(0, mention.start() - 60):mention.end() + 450]
        match = re.search(r"(?:supported values|allowed(?: values)?|permitted(?: values)?|"
                          r"expected(?: (?:one of|values?))?|should be|must be(?: one of)?|"
                          r"one of|valid values)\s*(?:are|is)?\s*[:=]?\s*(.+)", clause, re.I)
        if match:
            alternatives = re.split(r"[\n;}]", match.group(1), maxsplit=1)[0]
            sequence = re.match(r"\s*\[?\s*(['\"][A-Za-z][A-Za-z0-9_.-]*['\"]"
                                r"(?:(?:\s*,\s*(?:(?:or|and)\s+)?|\s+(?:or|and)\s+)"
                                r"['\"][A-Za-z][A-Za-z0-9_.-]*['\"])*)(?:\s*\])?", alternatives)
            values = re.findall(r"['\"]([A-Za-z][A-Za-z0-9_.-]*)['\"]", sequence.group(1)) if sequence else []
            if values:
                return _canonical_levels(values)
    return None


def _parameter_unsupported(error: object) -> bool:
    if not is_effort_rejection(error):
        return False
    text = _error_text(error)
    return bool(re.search(
        r"(?:unsupported|unknown|unrecognized|unexpected)\s+(?:request\s+)?(?:parameter|argument|field)"
        r"[^\n]{0,90}(?:effort)|(?:effort)[^\n]{0,90}"
        r"(?:parameter (?:is )?(?:unsupported|not supported)|is not supported|does not support)|"
        r"extra inputs are not permitted", text, re.I))


def detect_levels(request: Callable[[str | None], object]) -> dict:
    """Discover accepted values using a caller-controlled minimal request.

    The callback receives a raw effort, or None to omit the parameter. It must
    raise on an unsuccessful response. There are at most ten calls: one invalid
    value, the eight documented candidates, and a no-parameter baseline if needed.
    This function does not retry failures or choose token budgets.
    """
    invalid_accepted = False
    try:
        request(_INVALID_EFFORT)
        invalid_accepted = True
    except Exception as error:
        allowed = allowed_levels(error)
        if allowed is not None:
            return {"state": "known", "source": "probe", "levels": allowed}
        if _parameter_unsupported(error):
            try:
                request(None)
            except Exception as baseline_error:
                return {"state": "failed", "source": "probe", "levels": [],
                        "error": _error_text(baseline_error)}
            return {"state": "known", "source": "probe", "levels": [], "noParameter": True}
        if not is_effort_rejection(error):
            return {"state": "failed", "source": "probe", "levels": [], "error": _error_text(error)}
    accepted = []
    for level in EFFORT_CANDIDATES:
        try:
            request(level)
        except Exception as error:
            if not is_effort_rejection(error):
                result = {"state": "failed", "source": "probe", "levels": accepted,
                          "error": _error_text(error)}
                if invalid_accepted:
                    result["invalidAccepted"] = True
                return result
        else:
            accepted.append(level)
    result = {"state": "known", "source": "probe", "levels": accepted}
    if not accepted:
        try:
            request(None)
        except Exception as error:
            result.update(state="failed", error=_error_text(error))
        else:
            result["noParameter"] = True
    if invalid_accepted:
        result["invalidAccepted"] = True
    return result


def _level_result(probe, format: str, first: tuple[bool, object]) -> dict:
    """Finish effort acceptance discovery on the chosen wire, without guessing."""
    success, value = first
    if success:
        # vLLM's documented string schema is a useful unverified menu when a
        # gateway silently ignores even the deliberate invalid value. Do not
        # spend another eight requests proving the same acceptance-only fact.
        return {"state": "known", "source": "fallback", "levels": list(OPENROUTER_EFFORTS),
                "verified": False, "invalidAccepted": True}
    allowed = allowed_levels(value)
    if allowed is not None:
        return {"state": "known", "source": "probe", "levels": allowed, "verified": True}
    if not is_effort_rejection(value):
        return {"state": "failed", "source": "probe", "levels": [],
                "verified": False, "error": _error_text(value)}
    if _parameter_unsupported(value):
        success, baseline = probe("off", format, 1)
        if success:
            return {"state": "known", "source": "probe", "levels": [],
                    "verified": False, "noParameter": True}
        return {"state": "failed", "source": "probe", "levels": [],
                "verified": False, "error": _error_text(baseline)}
    accepted = []
    for level in EFFORT_CANDIDATES:
        success, error = probe(level, format, 1)
        if success:
            accepted.append(level)
        elif not is_effort_rejection(error):
            return {"state": "failed", "source": "probe", "levels": accepted,
                    "verified": False, "error": _error_text(error)}
    result = {"state": "known", "source": "probe", "levels": accepted, "verified": True}
    if not accepted:
        success, error = probe("off", format, 1)
        if success:
            result["noParameter"] = True
        else:
            result.update(state="failed", verified=False, error=_error_text(error))
    return result


def detect_model(request: Callable[[str, str, int], object], advertised_levels=None,
                 manual_levels=None, manual_format=None, protocol="openai",
                 caps=(1, 4, 16)) -> dict:
    """Discover independent effort acceptance and observable thinking controls.

    ``request(effort, format, max_tokens)`` returns a parser observation with
    ``thinking``/``content`` booleans (or positive ``*Chars`` counts). It raises
    an already-sanitized provider exception for unsuccessful responses. Results
    are facts from this bounded run, not guarantees of semantic effort strength.
    This module performs no HTTP, credential, configuration or cache I/O.
    """
    if manual_format is not None and not valid_format(manual_format):
        raise ValueError("Unknown thinking format")
    caps = tuple(dict.fromkeys(caps))
    if not caps or any(not isinstance(cap, int) or isinstance(cap, bool) or cap < 1 for cap in caps):
        raise ValueError("Output caps must be positive integers")
    initial = manual_format or (protocol if protocol in ("anthropic", "responses") else "openai")
    cache = {}
    blocked = []

    def probe(effort, format, cap):
        key = effort, format, cap
        if key not in cache:
            try:
                observation = request(effort, format, cap)
                cache[key] = True, observation
            except Exception as error:
                cache[key] = False, error
                status = getattr(error, 'status_code', None)
                if (status in (401, 403, 408, 429) or (isinstance(status, int) and status >= 500)
                        or re.search(r'unauthori[sz]ed|authentication|invalid.api.key|quota|rate.limit|'
                                     r'too many requests|timed?\s*out|timeout|connection|network|'
                                     r'insufficient.{0,12}(?:credit|balance)', _error_text(error), re.I)):
                    blocked.append(_error_text(error)[:500])
        return cache[key]

    def observed(value, name):
        return isinstance(value, Mapping) and (value.get(name) is True or
               (isinstance(value.get(name + "Chars"), (int, float)) and
                value[name + "Chars"] > 0))

    if manual_levels is not None:
        levels = {"state": "known", "source": "manual", "levels": list(manual_levels),
                  "verified": False}
        first = None
    elif advertised_levels is not None:
        declared = (metadata_levels(advertised_levels) if isinstance(advertised_levels, Mapping)
                    else _canonical_levels(advertised_levels))
        levels = ({"state": "known", "source": "metadata", "levels": declared,
                   "verified": False} if declared is not None else None)
        first = None if levels is not None else probe(_INVALID_EFFORT, initial, 1)
    else:
        levels = None
        first = probe(_INVALID_EFFORT, initial, 1)

    provisional = levels["levels"] if levels is not None else (
        allowed_levels(first[1]) if not first[0] else list(OPENROUTER_EFFORTS))
    available = [level for level in (provisional or []) if level != "none"]
    # Use the strongest documented canonical value for observation. Real APIs
    # can return empty thinking even at high; this is still an observation,
    # never a guarantee or a rewrite of the user's selected session effort.
    on_effort = next((level for level in ("max", "xhigh", "high", "medium") if level in available),
                     available[0] if available else "max")
    format_result = {"state": "unknown", "source": "probe", "format": None,
                     "verified": False, "onObserved": False, "offObserved": False,
                     "offVerified": False, "offSupported": None, "offFormat": None,
                     "status": "unknown", "onEffort": on_effort,
                     "formatsTried": [], "onAttempts": [], "offSwitchesTried": []}
    if manual_format is not None or protocol == "responses":
        format_result.update(state="known", source="manual" if manual_format else "protocol", format=initial)
    elif first is not None and not first[0] and not is_effort_rejection(first[1]):
        # Authentication, network and token-cap failures are not schema facts.
        format_result.update(state="failed", error=_error_text(first[1]))
    else:
        # Prefer explicit switches over an omitted parameter that happens to
        # return ordinary text. Compatible Anthropic hosts can also implement
        # the documented top-level/template controls; the native transport
        # retains them and maps effort to output_config.effort as usual.
        candidates = (("deepseek", "anthropic-adaptive", "qwen", "chat-template", "openai-none", "anthropic")
                      if protocol == "anthropic" else
                      ("qwen", "deepseek", "chat-template", "openai-none", "openai"))
        attempts = []
        last_error = None
        for candidate in candidates:
            on = {"format": candidate, "effort": on_effort, "status": "not-observable",
                  "thinkingObserved": False, "ordinaryContentObserved": False}
            candidate_effort = on_effort
            for cap in caps:
                ok, value = probe(candidate_effort, candidate, cap)
                if not ok:
                    declared = allowed_levels(value)
                    alternatives = ([level for level in declared if level != "none"]
                                    if declared is not None else available if provisional is not None
                                    else [level for level in EFFORT_CANDIDATES if level != "none"])
                    alternatives = sorted(alternatives, key=lambda level: _RANK.get(level, -1), reverse=True)
                    if is_effort_rejection(value) and not _parameter_unsupported(value):
                        # A validation error without an enum may reject medium
                        # while accepting low. Find an on request on this wire;
                        # do not misapply its acceptance set to another wire.
                        for alternative in alternatives:
                            if alternative == candidate_effort:
                                continue
                            candidate_effort = alternative
                            ok, value = probe(candidate_effort, candidate, cap)
                            if ok or not is_effort_rejection(value) or _parameter_unsupported(value):
                                break
                if not ok:
                    last_error = _error_text(value)
                    on.update(status="rejected", error=last_error[:500], outputCap=cap,
                              effort=candidate_effort)
                    break  # A rejected wire is not evidence against other wires.
                on.update(outputCap=cap, effort=candidate_effort,
                          ordinaryContentObserved=observed(value, "content"))
                if observed(value, "thinking"):
                    on.update(status="thinking", thinkingObserved=True)
                    break
            # Off is independent: an unobserved/rejected on request must not
            # prevent a documented off switch from ever reaching the server.
            off = {"format": candidate, "parameters": format_parameters(candidate, "off"),
                   "status": "not-observable", "thinkingObserved": False,
                   "ordinaryContentObserved": False}
            for cap in caps:
                ok, value = probe("off", candidate, cap)
                off['outputCap'] = cap
                if not ok:
                    off.update(status="rejected", error=_error_text(value)[:500])
                    break
                off.update(thinkingObserved=observed(value, "thinking"),
                           ordinaryContentObserved=observed(value, "content"))
                if observed(value, "thinking"):
                    off['status'] = 'still-thinking'
                    break
                if observed(value, "content"):
                    off['status'] = 'disabled'
                    break
            attempts.append((on, off))
        # When both work, prefer the native effort shape with an explicit none
        # over a compatible server extension. Omission is never this preference:
        # it may simply inherit the server's thinking-enabled default.
        pair_order = (('openai-none', *[name for name in candidates if name != 'openai-none'])
                      if protocol == 'openai' else candidates)
        paired = next(((on, off) for name in pair_order for on, off in attempts
                       if on['format'] == name and on['thinkingObserved']
                       and off['status'] == 'disabled'), None)
        best_off = paired[1] if paired else next((off for _, off in attempts if off['status'] == 'disabled'), None)
        best_on = paired[0] if paired else next((on for on, _ in attempts if on['thinkingObserved']), None)
        if best_off is None:
            # An always-thinking model can reject explicit disable switches.
            # Retain a usable legacy request when it has positive on evidence,
            # instead of making the existing off selection break normal chat.
            best_on = next((on for on, off in attempts if on['format'] == initial
                            and on['thinkingObserved'] and off['status'] != 'rejected'), best_on)
        format_result.update(state='known', format=best_on['format'] if best_on else initial,
            onObserved=best_on is not None, offObserved=best_off is not None,
            offVerified=best_off is not None, offSupported=best_off is not None,
            offFormat=best_off['format'] if best_off else None,
            verified=best_on is not None and best_off is not None,
            status=('on-not-observable' if best_on is None else
                    'on-off-verified' if best_off else 'cannot-disable'),
            onEffort=best_on['effort'] if best_on else on_effort,
            formatsTried=list(candidates), onAttempts=[on for on, _ in attempts],
            offSwitchesTried=[off for _, off in attempts])
        selected_caps = [part['outputCap'] for part in (best_on, best_off) if part]
        if selected_caps:
            format_result['outputCap'] = max(selected_caps)
        if not best_on and last_error:
            format_result['error'] = last_error[:500]
        if blocked:
            # A service failure during one of the extra switches cannot prove
            # that every documented off switch is unsupported.
            format_result.update(state='failed', status='unknown', verified=False,
                                 offVerified=False, offSupported=None, error=blocked[0])

    final_format = format_result["format"] or initial
    if levels is None:
        # Invalid values for top-level effort cannot describe a nested format.
        # Cache keeps an unchanged-wire failure from causing a duplicate call.
        final_first = first if final_format == initial else probe(_INVALID_EFFORT, final_format, 1)
        levels = _level_result(probe, final_format, final_first)
    return {"levels": levels, "format": format_result}
