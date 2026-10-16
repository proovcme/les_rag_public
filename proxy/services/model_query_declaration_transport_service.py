"""Optional native carrier for the existing model-authored query envelope."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from proxy.services.model_capability_service import CapabilityRequirementError, require_capabilities
from proxy.services.model_connection_contracts import CapabilityName
from proxy.services.context_governor_service import ContextRequiredSectionOverflow
from proxy.services.model_lsr_result_contract import decode_model_query_envelope

QUERY_DECLARATION_FUNCTION = 'declare_research_queries'


def resolve_query_declaration_transport(connection, *, now=None):
    """Reuse the assigned connection's existing capability evidence; never probe."""
    snapshot = getattr(connection, 'capability_snapshot', None)
    state = {'requested': 'capability_based', 'effective': 'text',
             'source': 'assigned_connection.capability_snapshot', 'restart_required': False,
             'connection_revision_id': str(getattr(connection, 'revision_id', '') or ''),
             'reason': 'capability_snapshot_unavailable'}
    if snapshot is None:
        return [], state
    observation = snapshot.observation(CapabilityName.TOOLS)
    state.update(capability_state=observation.state.value,
                 capability_evidence_source=observation.evidence_source,
                 capability_snapshot_id=snapshot.snapshot_id,
                 capability_observed_at=observation.observed_at.isoformat(),
                 capability_expires_at=snapshot.expires_at.isoformat())
    try:
        require_capabilities(snapshot, {CapabilityName.TOOLS}, now=now)
    except CapabilityRequirementError as error:
        state['reason'] = str(error)
        return [], state
    state.update(effective='native_function_optional', reason='existing_tools_requirement_satisfied')
    return [{'type': 'function', 'function': {
        'name': QUERY_DECLARATION_FUNCTION,
        'description': 'Declare the same search-query envelope for this technical phase; this does not execute searches or create document rows.',
        'parameters': {'type': 'object', 'properties': {
            'artifact_kind': {'type': 'string', 'enum': ['vor', 'lsr']},
            'queries': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}},
            'commentary': {'type': 'string'},
        }, 'required': ['queries'], 'additionalProperties': False},
    }}], state


def query_declaration_native_instruction(tools):
    if not tools:
        return ''
    return ('\nДля переноса того же JSON-конверта можешь вызвать declare_research_queries: '
            'arguments содержат queries, необязательные artifact_kind и commentary с тем же смыслом. '
            'Это только декларация, не поиск и не выпуск документа. Допустим один такой вызов '
            'либо прежний текстовый ответ; сам поисковые строки не меняй. Другие функции на этом этапе не предлагаются.')


def govern_query_declaration_messages(govern, *, native_tools=(), **context):
    """A schema-capacity fallback repacks the original text context before dispatch."""
    original = dict(context)
    capacity = {'requested_transport': 'native_function_optional' if native_tools else 'text',
                'effective_transport': 'native_function_optional' if native_tools else 'text',
                'reason': ''}
    if not native_tools:
        messages, packet = govern(**original)
        return messages, packet, [], capacity
    try:
        messages, packet = govern(**{**original, 'native_tools': native_tools,
            'profile_prefix': original['profile_prefix'] + query_declaration_native_instruction(native_tools)})
        return messages, packet, native_tools, capacity
    except ContextRequiredSectionOverflow as error:
        capacity.update(effective_transport='text', reason='native_query_schema_capacity',
                        code='CONTEXT_REQUIRED_SECTION_OVERFLOW', budget_tokens=error.budget,
                        required_tokens=error.required_tokens)
    # Same original directive, required evidence, source map and preset. If that
    # also overflows, its specific error propagates and no model is dispatched.
    messages, packet = govern(**original)
    return messages, packet, [], capacity


def query_declaration_response_text(raw_text: str, *, response=None, advertised=False):
    """Read only one recognized native envelope; all rejection data stays whole."""
    calls = tuple(getattr(response, 'tool_calls', ()) or ())
    visible = str(getattr(response, 'text', '') or '')
    trace = {'channel': 'text', 'advertised_native_function': bool(advertised),
             'native_call_count': len(calls), 'assistant_visible_chars': len(visible),
             'reason': ''}
    if not advertised or not calls:
        if calls:
            trace.update(channel='unadvertised_native', reason='legacy_text_path_unchanged')
        return raw_text, trace

    def rejected(reason):
        trace.update(channel='native_invalid', reason=reason)
        # Keep every call/name/raw argument and visible commentary. Never copy
        # response.reasoning_content into a query failure's visible snapshot.
        return json.dumps({'query_native_transport_error': reason,
                           'native_calls': [dict(call) for call in calls],
                           'assistant_content': visible}, ensure_ascii=False), trace

    if len(calls) != 1:
        return rejected('declaration_requires_one_native_call')
    function = calls[0].get('function')
    if not isinstance(function, Mapping) or function.get('name') != QUERY_DECLARATION_FUNCTION:
        return rejected('unexpected_native_function')
    arguments = function.get('arguments')
    if isinstance(arguments, str):
        raw_arguments = arguments
        representation = 'provider_json_string'
    elif isinstance(arguments, Mapping):
        try:
            raw_arguments = json.dumps(dict(arguments), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            return rejected('native_arguments_not_json_object')
        representation = 'provider_object_lossless_values'
    else:
        return rejected('native_arguments_not_json_object')
    if decode_model_query_envelope(raw_arguments) is None:
        return rejected('native_arguments_not_query_envelope')
    # The unchanged reader must still see any conflicting authored metadata or
    # commentary; do not silently discard visible content beside a native call.
    carrier = raw_arguments + ('\n\n' + visible if visible else '')
    trace.update(channel='native_function', arguments_representation=representation,
                 native_arguments_chars=len(raw_arguments),
                 native_arguments_sha256=hashlib.sha256(raw_arguments.encode('utf-8')).hexdigest())
    return carrier, trace
