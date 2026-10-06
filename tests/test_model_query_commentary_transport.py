"""Keep one authored query envelope beside harmless, separately authored commentary."""
import json

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services import model_lsr_result_contract as contract


# Exact second final_text from the public failed913 SKS query incident. The
# original receipt remains immutable; no model search or norm is authored here.
ACTUAL_REPAIR = '''```json
{
  "commentary": "Для формирования ВОР по спецификации СКС необходимо идентифицировать монтажные операции для каждой позиции оборудования и кабельных изделий. Поскольку исходник содержит специфические изделия (шкафы, организаторы, блоки розеток, патч-панели, патч-корды), запросы направлены на поиск соответствующих монтажных работ в справочниках и базах данных."
}
```
```json
{
  "queries": [
    "Монтаж шкафа напольного 19-дюймового",
    "Монтаж кабельного организатора",
    "Монтаж шины заземления",
    "Монтаж блока розеток",
    "Монтаж патч-панели",
    "Монтаж патч-корда",
    "Монтаж кабельно-несущих конструкций",
    "Монтаж оборудования СКС"
  ]
}
```'''
ACTUAL_QUERIES = [
    "Монтаж шкафа напольного 19-дюймового", "Монтаж кабельного организатора",
    "Монтаж шины заземления", "Монтаж блока розеток", "Монтаж патч-панели",
    "Монтаж патч-корда", "Монтаж кабельно-несущих конструкций", "Монтаж оборудования СКС",
]


def fenced(body):
    return '```json\n' + body + '\n```'


def test_actual_sks_repair_preserves_all_eight_queries_and_commentary_without_target_inference():
    decoded = contract.decode_model_query_envelope(ACTUAL_REPAIR)
    assert decoded is not None
    assert decoded['queries'] == ACTUAL_QUERIES
    declared = service.read_model_query_response(ACTUAL_REPAIR, finish_reason='stop')
    assert [query.text for query in declared['queries']] == ACTUAL_QUERIES
    assert declared['commentary'] == decoded['commentary']
    assert declared['commentary'].startswith('Для формирования ВОР по спецификации СКС')
    assert declared['artifact_kind_declaration']['status'] == 'missing'
    assert declared['artifact_kind_declaration']['artifact_kind'] == ''
    assert not declared['intentional_empty']
    assert declared['accompanying_answer'] == []
    diagnostic = service.declared_query_output_diagnostics(ACTUAL_REPAIR, declared)
    assert diagnostic['accepted_count'] == 8
    assert diagnostic['rejected_count'] == 0
    assert diagnostic['output_shape'] == 'query_envelope'


@pytest.mark.parametrize('side_first', [False, True])
@pytest.mark.parametrize('side_fenced', [False, True])
@pytest.mark.parametrize('target', [None, 'vor', 'lsr'])
def test_one_commentary_only_object_keeps_literal_order_spaces_duplicates_and_existing_metadata(
        side_first, side_fenced, target):
    queries = ['  Literal Ω "x"; 2,5 {a}  ', 'artifact_kind: vor', 'Repeated', 'Repeated']
    body = {'queries': queries, 'commentary': 'Envelope note\nexact second line'}
    if target is not None:
        body['artifact_kind'] = target
    side_note = 'Side note\n{"artifact_kind":"lsr"} is literal quoted commentary'
    query_text = fenced(json.dumps(body, ensure_ascii=False))
    side_text = json.dumps({'commentary': side_note}, ensure_ascii=False)
    if side_fenced:
        side_text = fenced(side_text)
    raw = '\n'.join((side_text, query_text) if side_first else (query_text, side_text))
    decoded = contract.decode_model_query_envelope(raw)
    assert decoded is not None and decoded['queries'] == queries
    expected_comments = [side_note, body['commentary']] if side_first else [body['commentary'], side_note]
    assert decoded['commentary'] == '\n\n'.join(expected_comments)
    declared = service.read_model_query_response(raw, finish_reason='stop')
    assert declared['accompanying_answer'] == []
    assert declared['artifact_kind_declaration']['status'] == ('declared' if target else 'missing')
    assert declared['artifact_kind_declaration']['artifact_kind'] == (target or '')
    assert not declared['intentional_empty']


@pytest.mark.parametrize('side', [
    '{"queries":["different"]}', '{"queries":["one"]}',
    '{"commentary":"x","queries":["different"]}',
    '{"commentary":"x","artifact_kind":"vor"}', '{"artifact_kind":"lsr"}',
    '{"commentary":"x","rows":[]}', '{"rows":[]}',
    '{"commentary":"x","unknown":true}', '{"commentary":null}',
    '{"commentary":12}', '{"commentary":{"text":"x"}}', '["commentary"]',
    '{"commentary":"x","commentary":"x"}', '{"commentary":"x","commentary":"y"}',
    '{"commentary":"x"', '{"commentary":"x"} trailing',
])
def test_unknown_business_duplicate_or_malformed_side_documents_remain_rejected(side):
    raw = fenced('{"queries":["one"],"artifact_kind":"lsr"}') + '\n' + fenced(side)
    assert contract.decode_model_query_envelope(raw) is None
    assert service.read_model_query_response(raw)['queries'] == []


@pytest.mark.parametrize('query', [
    '{"queries":["one"],"queries":["one"]}',
    '{"queries":["one"],"artifact_kind":"bad"}',
    '{"queries":["one"],"artifact_kind":"lsr","artifact_kind":"vor"}',
    '{"queries":["one"],"artifact_kind":"lsr","rows":[]}',
    '{"queries":["one"],"unknown":true}',
    '{"queries":["one",2]}', '{"queries":["one\\ntwo"]}',
    '{"payload":{"queries":["one"]}}', '{"queries":["one"]',
])
def test_commentary_side_does_not_legitimize_invalid_or_business_query_documents(query):
    raw = fenced(query) + '\n' + fenced('{"commentary":"harmless"}')
    assert contract.decode_model_query_envelope(raw) is None
    assert service.read_model_query_response(raw)['queries'] == []


def test_three_documents_or_conflicting_external_target_are_not_selected_or_merged():
    raw = fenced('{"queries":["one"],"artifact_kind":"lsr"}') + '\n' + fenced('{"commentary":"x"}')
    assert contract.decode_model_query_envelope(raw + '\n' + fenced('{"commentary":"y"}')) is None
    assert contract.decode_model_query_envelope(raw + '\nartifact_kind: vor') is None
    assert service.read_model_query_response(raw + '\nartifact_kind: vor')['queries'] == []


def test_empty_query_intent_rules_are_unchanged_with_harmless_side_commentary():
    side = '\n' + fenced('{"commentary":"No search needed"}')
    for target, intentional in [(None, False), ('lsr', False), ('vor', True)]:
        body = {'queries': []}
        if target is not None:
            body['artifact_kind'] = target
        raw = fenced(json.dumps(body)) + side
        declared = service.read_model_query_response(raw)
        assert declared['queries'] == []
        assert declared['intentional_empty'] is intentional


def test_commentary_object_plus_plain_query_lines_is_still_not_an_executable_envelope():
    raw = fenced('{"commentary":"Source note"}') + '\n1. Literal query Ω\n2. Another query'
    assert contract.decode_model_query_envelope(raw) is None
    assert service.read_model_query_response(raw)['queries'] == []
