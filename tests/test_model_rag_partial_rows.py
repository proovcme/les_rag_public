import pytest

from proxy.services import chat_evidence_application_service as chat
from proxy.services import rim_lsr_trace_service as rim
from proxy.services.portion_cursor_service import canonical_decision, decisions_revision


ANSWER = '''| source_row | title | unit | quantity | norm_code |
|---|---|---|---|---|
| 1 | Work | m | 2 | ГЭСН01-01-001-01 |
| 2 | Cable | m | 4 | supplier comment | unknown | |
'''


def test_bad_cells_preserve_other_rows_and_original_bad_row(monkeypatch):
    parsed = chat.parse_model_rag_result(ANSWER)
    assert parsed is not None
    text, rows = parsed
    assert text == ANSWER
    assert len(rows) == 2
    assert rows[0]['norm_code'] == 'ГЭСН01-01-001-01'
    assert rows[1]['source_row'] == 2
    assert rows[1]['parse_error'] == 'column_count_mismatch'
    assert rows[1]['raw_cells'] == ['2', 'Cable', 'm', '4', 'supplier comment', 'unknown', '']
    assert not rows[1].get('norm_code')
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda code: {'unit': 'm'})
    result = rim.positions_from_visible_lsr_rows(rows)
    assert len(result['positions']) == 1
    assert result['row_bindings'][1]['status'] == 'model_row_format_error'
    saved = canonical_decision(rows[1])
    assert saved['raw_cells'] == rows[1]['raw_cells']
    changed = dict(rows[1], raw_cells=['different authored cells'])
    assert decisions_revision([changed]) != decisions_revision([rows[1]])


def test_bad_row_without_leading_identity_remains_ambiguous():
    answer = '''| title | source_row | unit | norm_code |
|---|---|---|---|
| Unescaped | title | 2 | m | N |
'''
    assert chat.parse_model_rag_result(answer) is None


def test_nonnumeric_coefficient_is_visible_in_diagnostics(monkeypatch):
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda code: {'unit': 'm'})
    value = 'conversion_factor=100, conversion_unit=шт, conversion_source=manufacturer'
    result = rim.positions_from_visible_lsr_rows([dict(
        source_row=1, title='Work', unit='m', quantity=2,
        norm_code='ГЭСН01-01-001-01', coefficient=value,
    )])
    binding = result['row_bindings'][0]
    assert binding['coefficient_status'] == 'needs_basis'
    assert binding['proposed_coefficient'] == value
    assert result['positions'][0]['qty'] == 2


def test_repeated_numbered_queries_are_executed_once_without_losing_unique_queries():
    raw = 'Поисковые запросы к выбранным датасетам:\n1. монтаж шкафа\n2. монтаж кабеля\n3. монтаж шкафа\n4. ГЭСНм10-01-055-02'
    assert chat.parse_model_rag_queries(raw) == [
        'монтаж шкафа', 'монтаж кабеля', 'ГЭСНм10-01-055-02',
    ]
    distinct = [f'монтаж элемента {n}' for n in range(75)]
    assert chat.parse_model_rag_queries('\n'.join(distinct)) == distinct


def test_extra_divider_and_trailing_empty_cells_are_lossless():
    raw = '''| source_row | title | unit | quantity | norm_code | evidence_refs |
|---|---|---|---|---|---|---|
| 1 | Work | m | 2 | ГЭСН01-01-001-01 | Q1.H1 | |
'''
    parsed = chat.parse_model_rag_result(raw)
    assert parsed is not None
    assert parsed[0] == raw
    assert parsed[1][0]['norm_code'] == 'ГЭСН01-01-001-01'
    assert parsed[1][0]['evidence_refs'] == ['Q1.H1']
    assert parsed[1][0]['quantity'] == 2
    bad = raw.replace('Q1.H1 | |', 'Q1.H1 | ambiguous |')
    parsed_bad = chat.parse_model_rag_result(bad)
    assert parsed_bad[1][0]['parse_error'] == 'column_count_mismatch'
    assert parsed_bad[1][0]['raw_cells'][-1] == 'ambiguous'


# --- Живая проверка 17.09, проход 3 -------------------------------------------------------
# У строки работы СКС!5.6 модель поставила одну лишнюю пустую ячейку. Ошибка формата задумана
# неблокирующей: строка не считается и возвращается модели со своими ячейками. Но у такой
# строки нет work_id, и соседняя поставка той же позиции получала «номер повторён» и «не
# соответствует порции» — порция из трёх строк отвергалась целиком, а модель в сообщении
# видела не ту причину.

OPERATIONS = '''| source_row | work_id | title | unit | quantity | norm_code | evidence_refs |
|---|---|---|---|---|---|---|
| СКС!5.6 | lay | Прокладка | 100 м | 85 | ГЭСНм10-01-055-02 | | Q1.H1 |
| СКС!5.6 | supply | Кабель витая пара | м | 8500 | — | |
| АР!1.31 | floor | Покрытие | м2 | 66.7 | — | |
'''


def test_unreadable_operation_does_not_make_its_siblings_duplicates():
    rows = chat.parse_model_rag_result(OPERATIONS)[1]
    assert rows[0]['parse_error'] == 'column_count_mismatch'
    errors = chat.validate_model_rag_result_structure(rows, [], expected_source_rows=2)
    assert errors == ['model_row_format_error:СКС!5.6'], errors
    assert chat.blocking_model_rag_result_errors(errors) == []


def test_unreadable_operation_does_not_break_the_portion_check():
    rows = chat.parse_model_rag_result(OPERATIONS)[1]
    state = {'source_anchors': ['СКС!5.6', 'АР!1.31'], 'shown': ['СКС!5.6', 'АР!1.31']}
    assert chat.portion_structure_errors(rows, state) == []
    foreign = rows + [dict(rows[0], source_row='ОВ!9.9')]
    assert chat.portion_structure_errors(foreign, state) == ['invalid_portion_source_row:ОВ!9.9']


# --- Живая проверка 17.09, проход 5 -------------------------------------------------------
# Модель выбрала норму работы СКС!5.6 без ссылки на карточку (и с опечаткой в шифре), и вся
# порция из трёх строк была отвергнута — вместе с первой найденной нормой демонтажа
# оповещателя. Норма без ссылки по-прежнему не считается; но отказ адресуется этой строке,
# а не всей порции.

UNREFERENCED = '''| source_row | work_id | title | unit | quantity | norm_code | evidence_refs |
|---|---|---|---|---|---|---|
| СКС!5.6 | lay | Прокладка | м | 8500 | ГЭСНм08-03-398-01 | |
| СОУЭ!7.2 | dismantle | Демонтаж оповещателя | шт | 7 | ГЭСНм10-04-101-07 | Q1.H1 |
'''


def test_norm_without_evidence_is_withheld_row_by_row(monkeypatch):
    rows = chat.parse_model_rag_result(UNREFERENCED)[1]
    errors = chat.validate_model_rag_result_structure(rows, [], expected_source_rows=2)
    assert 'missing_evidence_ref:СКС!5.6' in errors
    assert not [e for e in chat.blocking_model_rag_result_errors(errors) if e.startswith('missing_evidence_ref')]
    withheld = chat.withhold_unreferenced_norms(rows)
    assert withheld[0]['evidence_error'] == 'missing_evidence_ref'
    assert 'evidence_error' not in withheld[1]
    assert 'evidence_error' not in rows[0], 'исходные строки модели не меняются'
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda code: {'unit': 'шт'})
    result = rim.positions_from_visible_lsr_rows(withheld)
    assert result['row_bindings'][0]['status'] == 'evidence_ref_required'
    assert [p['work_id'] for p in result['positions']] == ['dismantle']


def test_withheld_row_is_explained_and_kept_between_passes():
    from proxy.services.portion_cursor_service import DECISION_FIELDS

    assert 'evidence_error' in DECISION_FIELDS
    assert 'evidence_refs' in chat._rejection_wording('evidence_ref_required')


# --- Сравнение моделей 17.09: порядок колонок и сдвиг полей в короткой строке -------------
# Все модели сбивались со счёта пустых ячеек, когда nr_sp_rule_id стоял после девяти редко
# заполняемых колонок. Частые колонки идут первыми, редкие — в конце: пустые ячейки уходят
# в хвост, который разбор отбрасывает без потерь. А короткая строка, у которой пропущена
# ячейка в середине, молча сдвигала поля: количество 8500 оказывалось кодом ресурса.

def test_contract_lists_frequent_extra_columns_before_rare_ones():
    text = chat.model_answer_request('Смета', model_driven=True)
    listing = text.split('К базовой шапке добавь отдельные колонки', 1)[1]
    order = ['decision_kind', 'nr_sp_rule_id', 'resource_review_status', 'resource_review_ref',
             'resource_code', 'resource_quantity', 'resource_unit',
             'included_in', 'resource_action', 'target_resource_code', 'replaced_by',
             'conversion_factor', 'conversion_unit', 'conversion_source']
    positions = [listing.index(name) for name in order]
    assert positions == sorted(positions), dict(zip(order, positions))


SHIFTED = '''| source_row | work_id | title | unit | quantity | norm_code | decision_kind | resource_code | resource_quantity | resource_unit | nr_sp_rule_id |
|---|---|---|---|---|---|---|---|---|---|---|
| СКС!5.6 | supply | Кабель | м | 8500 | | самостоятельный материал | 8500 | м | |
| СКС!5.7 | lay | Прокладка | 100 м | 85 | ГЭСНм10-01-055-02 | работа | | | |
'''


def test_short_row_with_a_shifted_field_is_a_format_error_not_a_guess():
    rows = chat.parse_model_rag_result(SHIFTED)[1]
    assert rows[0]['parse_error'] == 'column_count_mismatch', rows[0]
    assert rows[0]['raw_cells'][7] == '8500'
    assert not rows[1].get('parse_error'), 'пропущенные хвостовые пустые ячейки — не ошибка'
    assert rows[1]['norm_code'] == 'ГЭСНм10-01-055-02'


def test_review_columns_are_part_of_the_ordered_listing():
    """Проход 2 на IQ2_M: «строго в этом порядке, лишних не добавляй» без колонок подтверждения
    — и модель не подтвердила ни одного чека."""
    text = chat.model_answer_request('Смета', model_driven=True)
    listing = text.split('К базовой шапке добавь отдельные колонки', 1)[1].split('.', 1)[0]
    for name in ('resource_review_status', 'resource_review_ref', 'material_review_status', 'material_review_reason'):
        assert name in listing, name


# --- Проход 3 на IQ2_M: ссылка на несуществующую карточку ---------------------------------
# Модель записала ссылки номером строки ведомости (Q7.2.H1, Q1.31.H1). Таких карточек в проходе
# нет, и порция отвергалась целиком — вместе с впервые подтверждёнными чеками. Норма, которую
# не подкрепляет ни одна из показанных карточек, по-прежнему не считается, но отказ — построчный.

INVENTED = '''| source_row | work_id | title | unit | quantity | norm_code | evidence_refs | decision_kind |
|---|---|---|---|---|---|---|---|
| СОУЭ!7.2 | dismantle | Демонтаж | шт | 7 | ГЭСНм10-08-001-10 | Q7.2.H1 | работа |
| СКС!5.6 | lay | Прокладка | м | 8500 | ГЭСНм08-02-398-01 | Q1.H3, Q9.H9 | работа |
| СКС!5.6 | supply | Кабель | м | 8500 | | Q42.H1 | самостоятельный материал |
'''


def test_norm_backed_only_by_unknown_cards_is_withheld_row_by_row(monkeypatch):
    rows = chat.parse_model_rag_result(INVENTED)[1]
    withheld = chat.withhold_unreferenced_norms(
        rows, delivered_cards={'Q1.H3': 'ГЭСНм08-02-398-01', 'Q7.H2': 'ГЭСНм10-04-101-07'})
    assert withheld[0]['evidence_error'] == 'unknown_evidence_ref'
    assert 'evidence_error' not in withheld[1], 'доставленная карточка подтверждает этот шифр'
    assert 'evidence_error' not in withheld[2], 'ссылка материала не подкрепляет норму'
    errors = chat.validate_model_rag_result_structure(rows, [], expected_source_rows=2)
    assert any(error.startswith('unknown_evidence_ref:') for error in errors)
    assert not [e for e in chat.blocking_model_rag_result_errors(errors) if e.startswith('unknown_evidence_ref')]
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda code: {'unit': 'шт'})
    result = rim.positions_from_visible_lsr_rows(withheld)
    assert result['row_bindings'][0]['status'] == 'evidence_ref_unknown'
    assert 'Q7.2.H1' not in chat._rejection_wording('evidence_ref_unknown')
    assert 'Qx.Hy' in chat._rejection_wording('evidence_ref_unknown')


# --- Аудит Codex 17.09 по .141: ссылка должна подтверждать именно выбранный шифр ----------
# В .141 любая настоящая ссылка рядом с выдуманной пропускала строку в расчёт, даже если её
# карточка — про другую норму. Проверяется соответствие шифра конкретной доставленной
# карточке; известность идентификатора ничего не подтверждает.

from types import SimpleNamespace

CARD_MISMATCH = '''| source_row | work_id | title | unit | quantity | norm_code | evidence_refs | decision_kind |
|---|---|---|---|---|---|---|---|
| СКС!5.6 | lay | Прокладка | м | 8500 | ГЭСНм08-02-398-01 | Q1.H1, Q7.2.H1 | работа |
| СКС!5.7 | lay2 | Прокладка | м | 100 | ГЭСНм10-01-055-02 | Q2.H1 | работа |
| СКС!5.8 | lay3 | Прокладка | м | 100 | ГЭСНм10-01-055-02 | Q5.H1 | работа |
'''
DELIVERED = {'Q1.H1': 'ГЭСНм08-02-146-01', 'Q2.H1': 'ГЭСНм10-01-055-02'}


def test_reference_must_support_the_selected_code_not_merely_exist(monkeypatch):
    rows = chat.parse_model_rag_result(CARD_MISMATCH)[1]
    withheld = chat.withhold_unreferenced_norms(rows, delivered_cards=DELIVERED)
    assert withheld[0]['evidence_error'] == 'norm_code_not_in_referenced_evidence', withheld[0]
    assert 'evidence_error' not in withheld[1], 'карточка подтверждает именно этот шифр'
    assert withheld[2]['evidence_error'] == 'unknown_evidence_ref', 'карточка не доставлена'
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda code: {'unit': 'м'})
    bindings = rim.positions_from_visible_lsr_rows(withheld)['row_bindings']
    assert [b['status'] for b in bindings] == ['evidence_card_mismatch', 'bound', 'evidence_ref_unknown']
    assert 'другой норме' in chat._rejection_wording('evidence_card_mismatch')


def test_delivered_cards_are_taken_from_the_packet_not_from_all_found_chunks():
    chunks = [SimpleNamespace(meta={'model_evidence_ref': 'Q3.H1', 'norm_code': 'ГЭСН11-01-038-05'}),
              SimpleNamespace(meta={'model_evidence_ref': 'Q90.H1', 'norm_code': 'ГЭСНм10-01-055-02'})]
    packet_text = '[Поисковый запрос Q3] демонтаж\n[Q3.H1 | smeta_norm_cards.v1 | score=6.0]:\nШифр: ГЭСН11-01-038-05\n'
    assert chat.delivered_evidence_cards(packet_text, chunks) == {'Q3.H1': 'ГЭСН11-01-038-05'}


def test_trace_group_ids_are_the_labels_the_model_actually_saw():
    """Трасса прохода 3 писала Q1-Q14, а модель получила Q3-Q16: два разных множества."""
    hits = [(f'запрос {n}', [SimpleNamespace(content='x' * 200, doc_name='smeta_norm_cards.v1', score=1.0,
                                             meta={'norm_code': f'ГЭСН01-01-001-{n:02d}'})]) for n in range(1, 6)]
    groups, _chunks = chat.build_model_rag_evidence_groups(hits, max_chars=100000, hits_per_query=1)
    assert chat.evidence_group_ids(groups) == ['Q1', 'Q2', 'Q3', 'Q4', 'Q5']
    # governor отбрасывает начало пакета: доставлено не то, что собрано.
    delivered_text = chr(10).join(groups[2:])
    assert chat.delivered_group_ids(delivered_text) == ['Q3', 'Q4', 'Q5']
    assert chat.delivered_group_ids('') == []


# --- Повторный аудит Codex 17.09 (R1.3) ---------------------------------------------------
# 1) «…-05 (аналог …-02)» проходило проверку по карточке …-02, а расчёт брал …-05:
#    подтверждалась одна норма, считалась другая. Сравнивается ровно тот шифр, который
#    получит расчёт, а два разных шифра в одном поле — конфликт формата.
# 2) Упаковщик заменяет повтор карточки на «См. Q1.H1», и governor может доставить только
#    её: ссылка без оригинала подтверждала выбор.

ALIAS_PACKET = ('[Поисковый запрос Q2] прокладка\n'
                '[Q2.H1 | smeta_norm_cards.v1 | score=1.0000]: См. Q1.H1: тот же текст и источник.\n')
FULL_PACKET = ('[Поисковый запрос Q1] прокладка\n'
               '[Q1.H1 | smeta_norm_cards.v1 | score=2.0000]:\nШифр: ГЭСНм10-01-055-02\n\n') + ALIAS_PACKET
ALIAS_CHUNKS = [SimpleNamespace(meta={'model_evidence_ref': 'Q1.H1', 'norm_code': 'ГЭСНм10-01-055-02'}),
                SimpleNamespace(meta={'model_evidence_ref': 'Q2.H1', 'norm_code': 'ГЭСНм10-01-055-02'})]


def _row(code, refs, work_id='w1'):
    return dict(source_row=1, work_id=work_id, title='Работа', unit='шт', quantity=2,
                norm_code=code, decision_kind='работа', evidence_refs=refs)


def test_confirmed_code_must_be_the_code_the_calculation_uses(monkeypatch):
    cards = {'Q1.H1': 'ГЭСН11-01-038-02'}
    rows = [_row('ГЭСН11-01-038-05 (аналог ГЭСН11-01-038-02)', ['Q1.H1'], 'w1'),
            _row('ГЭСН11-01-038-02 (Аналог: плитки на клее)', ['Q1.H1'], 'w2')]
    withheld = chat.withhold_unreferenced_norms(rows, delivered_cards=cards)
    assert withheld[0]['evidence_error'] == 'ambiguous_norm_code', withheld[0]
    assert 'evidence_error' not in withheld[1], 'один шифр и пояснение текстом — не конфликт'
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda code: {'unit': 'шт'})
    bindings = rim.positions_from_visible_lsr_rows(withheld)['row_bindings']
    assert [b['status'] for b in bindings] == ['norm_code_ambiguous', 'bound']
    assert 'analogue' in chat._rejection_wording('norm_code_ambiguous')


def test_alias_card_without_its_original_is_not_delivered_evidence(monkeypatch):
    assert chat.delivered_evidence_cards(ALIAS_PACKET, ALIAS_CHUNKS) == {}
    assert chat.delivered_evidence_cards(FULL_PACKET, ALIAS_CHUNKS) == {
        'Q1.H1': 'ГЭСНм10-01-055-02', 'Q2.H1': 'ГЭСНм10-01-055-02'}
    withheld = chat.withhold_unreferenced_norms(
        [_row('ГЭСНм10-01-055-02', ['Q2.H1'])],
        delivered_cards=chat.delivered_evidence_cards(ALIAS_PACKET, ALIAS_CHUNKS))
    assert withheld[0]['evidence_error'] == 'unknown_evidence_ref'
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda code: {'unit': 'шт'})
    assert rim.positions_from_visible_lsr_rows(withheld)['positions'] == []


# --- Проход 4 на 0.30.142: что держит три проверочные строки ------------------------------
# 1) Чек не подтверждается: модель пишет в resource_review_ref слово «calculation_ref», как в
#    инструкции, а не значение поля из чека. 2) В coefficient модель пишет область действия
#    («labor,machines»), и строка уходит в coefficient_basis_required, хотя коэффициента нет:
#    названия компонентов и число — непересекающиеся словари, это адресуемый разбор.

def test_receipt_instruction_asks_for_the_value_not_the_word():
    from proxy.smeta_core.calculation_receipt import receipt_context

    receipt = receipt_context([{'work_id': 'x', 'calculation_ref': 'a' * 64}])
    contract = chat.model_answer_request('Смета', model_driven=True)
    for text in (receipt, contract):
        assert 'значение calculation_ref' in text, text[:80]
        assert 'resource_review_ref=calculation_ref' not in text


def test_components_written_into_coefficient_are_read_as_its_target():
    raw = ('| source_row | work_id | title | unit | quantity | norm_code | coefficient | coefficient_target | evidence_refs |\n'
           '|---|---|---|---|---|---|---|---|---|\n'
           '| СКС!5.6 | lay | Прокладка | 100 м | 85 | ГЭСНм08-02-398-01 | labor,machines | | Q1.H2 |\n'
           '| СКС!5.7 | lay2 | Прокладка | 100 м | 85 | ГЭСНм08-02-398-01 | 1.15 | labor | Q1.H2 |\n')
    rows = chat.parse_model_rag_result(raw)[1]
    assert 'coefficient' not in rows[0], rows[0]
    assert rows[0]['coefficient_target'] == 'labor,machines'
    assert rows[1]['coefficient'] == 1.15 and rows[1]['coefficient_target'] == 'labor'


# --- Проход 5: оборванный список запросов и формат ссылки ---------------------------------
# Проходы 3 и 5 дали побайтово одинаковые 87 запросов и ровно 1600 completion-токенов —
# потолок генерации: список оборван, а не закончен. Выполнялись все 87 (20 минут), при этом
# в окно попадали только первые, и строки порции оставались без карточек. Код не придумывает
# запросы и не группирует их по темам: он выполняет бюджет по строкам порции и честно
# показывает модели, что осталось невыполненным, сохраняя номера и текст.

def test_query_plan_keeps_a_budget_per_portion_row_and_reports_the_rest():
    queries = [f'Демонтаж вариант {n}' for n in range(1, 88)]
    plan = chat.plan_model_rag_queries(queries, rows_in_pass=2, truncated=True)
    assert plan['executed'] == queries[:plan['budget']]
    assert plan['budget'] == 8 and len(plan['skipped']) == 79
    assert plan['skipped'][0] == {'index': 9, 'query': 'Демонтаж вариант 9'}
    assert plan['truncated'] is True
    note = chat.model_rag_query_plan_note(plan)
    assert '8 из 87' in note and 'оборван' in note and 'Демонтаж вариант 9' in note


def test_short_query_list_is_executed_whole_and_needs_no_note():
    plan = chat.plan_model_rag_queries(['цена: кабель', 'прокладка кабеля'], rows_in_pass=3, truncated=False)
    assert plan['executed'] == ['цена: кабель', 'прокладка кабеля'] and plan['skipped'] == []
    assert chat.model_rag_query_plan_note(plan) == ''


def test_contract_spells_out_the_evidence_reference_format():
    text = chat.model_answer_request('Смета', model_driven=True)
    assert 'Qn.Hm' in text and 'Q3.H1' in text
    assert 'номер строки ведомости' in text


def test_field_shape_is_checked_in_every_row_not_only_short_ones():
    """Проход 17: в resource_code попал обрывок хэша чека, длина строки была правильной."""
    raw = ('| source_row | work_id | title | unit | quantity | norm_code | decision_kind | resource_code | resource_quantity |\n'
           '|---|---|---|---|---|---|---|---|---|\n'
           '| АР!1.31 | m1 | Плитка | м2 | 66.7 | | материал | 1e845ec3f95a410569 | 66.7 |\n'
           '| АР!1.31 | m2 | Плитка | м2 | 66.7 | | материал | 01.6.03.03-0011 | 66.7 |\n')
    rows = chat.parse_model_rag_result(raw)[1]
    assert rows[0]['parse_error'] == 'column_count_mismatch', rows[0]
    assert rows[0]['raw_cells'][7] == '1e845ec3f95a410569'
    assert rows[1]['resource_code'] == '01.6.03.03-0011' and 'parse_error' not in rows[1]


# --- Проход 18: широкая таблица и молча потерянная вторая таблица --------------------------
# Модель промахивается по ячейкам 27-колоночной таблицы. Разнести работы и материалы по
# отдельным узким таблицам она не могла: шапка без norm_code не распознавалась, и строки
# материалов исчезали без единой ошибки.

TWO_TABLES = '''Работы:

| source_row | work_id | title | unit | quantity | norm_code | nr_sp_rule_id | resource_review_ref | evidence_refs |
|---|---|---|---|---|---|---|---|---|
| СКС!5.6 | lay | Прокладка | 100 м | 85 | ГЭСНм08-02-398-01 | nrsp-49.3 | a1b2c3 | Q1.H3 |

Материалы:

| source_row | work_id | title | unit | quantity | decision_kind | resource_code | resource_quantity | resource_unit |
|---|---|---|---|---|---|---|---|---|
| СКС!5.6 | supply | Кабель витая пара | м | 8500 | материал | 21.1.04.01-1046 | 8500 | м |
'''


def test_work_and_material_tables_are_both_read():
    rows = chat.parse_model_rag_result(TWO_TABLES)[1]
    assert [row['work_id'] for row in rows] == ['lay', 'supply']
    assert rows[0]['norm_code'] == 'ГЭСНм08-02-398-01' and rows[0]['nr_sp_rule_id'] == 'nrsp-49.3'
    assert rows[1]['resource_code'] == '21.1.04.01-1046' and rows[1]['decision_kind'] == 'материал'
    assert 'parse_error' not in rows[1]


def test_a_card_listing_is_not_mistaken_for_a_decision_table():
    raw = TWO_TABLES + '''
| Шифр | Измеритель | Наименование нормы |
|---|---|---|
| ГЭСН11-01-038-02 | 100 м2 | Устройство покрытий |
'''
    assert [row['work_id'] for row in chat.parse_model_rag_result(raw)[1]] == ['lay', 'supply']


def test_contract_allows_splitting_works_and_materials():
    text = chat.model_answer_request('Смета', model_driven=True)
    assert 'отдельными таблицами' in text and 'базовую шапку' in text


@pytest.mark.parametrize('field', ['section', 'operation', 'analogue', 'coverage', 'not_covered'])
def test_answer_contract_declares_each_requested_semantic_column(field):
    """Live .186 copied the exhaustive column list, omitting requested explanations."""
    text = chat.model_answer_request('Смета', model_driven=True)
    listed = text.split('полей строго в этом порядке: ', 1)[1].split('. Колонку', 1)[0]
    assert field in [column.strip() for column in listed.split(',')]


def test_semantic_columns_preserve_model_explanation_without_selecting_norms():
    values = dict(source_row='Fixture!3', work_id='work', title='Исходная работа',
                  unit='шт', quantity='7', norm_code='', evidence_refs='',
                  section='Раздел', operation='демонтаж', analogue='Подходящий аналог не выбран',
                  coverage='Объём исходника', not_covered='Норма и ресурсы неизвестны')
    columns = list(values)
    table = '\n'.join(['| ' + ' | '.join(columns) + ' |',
                       '|' + '|'.join('---' for _ in columns) + '|',
                       '| ' + ' | '.join(values.values()) + ' |'])
    _, rows = chat.parse_model_rag_result(table)
    assert len(rows) == 1 and not rows[0].get('parse_error')
    for field in ('section', 'operation', 'analogue', 'coverage', 'not_covered'):
        assert rows[0][field] == values[field]
    assert not rows[0].get('norm_code') and rows[0]['quantity'] == 7


def test_answer_contract_does_not_require_one_table_and_allow_multiple():
    text = chat.model_answer_request('Смета', model_driven=True)
    assert 'отдельными таблицами' in text
    assert 'одной таблицей' not in text
@pytest.mark.parametrize('rows_in_pass,budget', [(0, 8), (2, 8), (3, 12), (7, 28)])
def test_query_instruction_discloses_the_executor_budget(rows_in_pass, budget):
    queries = [f'original query {n}' for n in range(50)]
    plan = chat.plan_model_rag_queries(queries, rows_in_pass=rows_in_pass)
    instruction = chat.model_rag_query_instruction({'mode': 'estimator'}, rows_in_pass=rows_in_pass)
    assert f'до {budget} первых запросов' in instruction
    assert 'фиксированного лимита нет' not in instruction
    assert 'Сначала охвати содержательные позиции работ и материалов порции' in instruction
    assert plan['budget'] == budget
    assert plan['executed'] == queries[:budget]
    assert [item['query'] for item in plan['skipped']] == queries[budget:]
