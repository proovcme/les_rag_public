from copy import deepcopy

import pytest

from proxy.services.chat_evidence_application_service import _bind_smeta_discipline


@pytest.mark.parametrize('mode,frequency', [('none', False), ('frequency', True), ('similar', False), ('both', True)])
def test_experiment_cannot_leak_frequency_from_search_cards(mode, frequency):
    payload = {'cards': [{'norm_code': 'N2', 'usage_evidence': {'note': 'archive'}},
                         {'norm_code': 'N1', 'usage_evidence': {'note': 'archive'}}],
               'usage_discipline': 'communications', 'retrieval_trace': {'fusion': 'rrf'}}
    before = deepcopy(payload)
    retrieve = _bind_smeta_discipline(lambda q, limit: payload, question='',
                                     attachment_context='', practice_mode=mode)
    result = retrieve('physical operation', limit=2)
    assert [c['norm_code'] for c in result['cards']] == ['N2', 'N1']
    assert result['retrieval_trace'] == before['retrieval_trace']
    assert all(('usage_evidence' in c) == frequency for c in result['cards'])
    assert ('usage_discipline' in result) == frequency
    assert payload == before


def test_practice_experiment_is_explicit_validated_request_field():
    from pydantic import ValidationError
    from proxy.routers.chat import ChatRequest
    assert ChatRequest(question='q', smeta_practice_mode='none').model_dump()['smeta_practice_mode'] == 'none'
    assert ChatRequest(question='q').smeta_practice_mode == 'both'
    with pytest.raises(ValidationError):
        ChatRequest(question='q', smeta_practice_mode='secret')
