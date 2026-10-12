"""Модель может снять ресурс нормы, который заменяется изделием проекта.

ЗАЧЕМ. Норма приносит свой материал, и он считается деньгами как проектный.
Живой прогон 14–15.09, АР!1.31 «Ковровая плитка Atlas 05, 66,7 м²»: норма
ГЭСН11-01-038-02 посчитала «Плитка ПВХ для полов, толщина 1,2 мм» 68,034 м²
по 318,23 ₽ базы × 1,21 = 26 197,17 ₽ из 108 223,97 ₽ позиции. Это не открытая
позиция без цены, а уверенные деньги за другой товар.

ЧЕГО НЕ ХВАТАЛО. `included` распределяет количество УЖЕ имеющегося ресурса,
самостоятельный материал добавляет отдельную позицию. Ни один путь не убирает
исходный материал нормы, поэтому добавить проектное изделие рядом значило бы
посчитать покрытие дважды (ревью Codex 15.09).

ЧТО ЗДЕСЬ. Явное решение модели по исходному ресурсу: `resource_action=excluded`
снимает названный материал нормы. Норму, состав работ и остальные ресурсы код не
трогает; проектное изделие модель добавляет отдельной операцией тем путём, который
уже проверен в test_smeta_multiple_operations.
"""
from types import SimpleNamespace

from proxy.services import chat_evidence_application_service as chat
from proxy.services import rim_lsr_trace_service as rim


NORM = {
    'name': 'Устройство покрытий из плиток',
    'unit': '100 м2', 'nr_pct': 0, 'sp_pct': 0,
    'resources': [
        dict(kind='labor', code='L-FIX', name='Труд укладчика', unit='чел.-ч', per_unit=2),
        dict(kind='material', code='M-PVC', name='Плитка ПВХ для полов', unit='м2', per_unit=102),
        dict(kind='material', code='M-GLUE', name='Мастика клеящая', unit='кг', per_unit=52),
    ],
}
PRICES = [dict(code='L-FIX', unit='чел.-ч', price_current=10),
          dict(code='M-PVC', unit='м2', price_current=300),
          dict(code='M-GLUE', unit='кг', price_current=100)]

HEADER = ('| source_row | work_id | title | unit | quantity | norm_code | decision_kind | included_in '
          '| resource_action | target_resource_code | resource_code | evidence_refs | replaced_by | coverage |\n'
          '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n')
WORK = ('| АР!1.31 | lay | Устройство покрытия | м2 | 100 | ГЭСН11-01-038-02 | работа | — '
        '| — | — | — | Q1.H1 | — | — |\n')
DROP = ('| АР!1.31 | drop | Плитка ПВХ не применяется | м2 | 100 | — | ресурс | lay '
        '| excluded | M-PVC | — | | supply | — |\n')
# Снятие без решения о замене: ни поставки, ни обоснованного отсутствия потребности.
DROP_UNLINKED = DROP.replace('| supply | — |', '| — | — |')


def _run(raw, monkeypatch, *, prices=None):
    """Разобрать таблицу модели и посчитать её тем же путём, что и production."""
    from proxy.services.fgis_price_service import PriceBook
    from proxy.smeta_core.calculation_receipt import calculation_receipts

    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda _: dict(NORM))
    pricebook = PriceBook(prices or PRICES)
    parsed = chat.parse_model_rag_result(raw)
    assert parsed is not None, 'таблица модели должна разбираться'
    _text, rows = parsed
    evidence = [SimpleNamespace(meta={'model_evidence_ref': 'Q1.H1', 'norm_code': 'ГЭСН11-01-038-02'})]
    assert chat.validate_model_rag_result_structure(rows, evidence, expected_source_rows=1) == []
    trace = rim.build_lsr_trace_from_visible_rows(rows, pricebook=pricebook)
    receipts = {str(item['work_id']): (item.get('calculation') or {})
                for item in calculation_receipts(trace, pricebook=pricebook)}
    return trace, receipts


def _costs(calculation):
    return {str(item.get('code')): float(item.get('known_cost') or 0)
            for item in (calculation.get('resources') or [])}


def test_excluded_removes_the_named_norm_material(monkeypatch):
    """Снятый ресурс перестаёт стоить денег, остальной состав нормы не меняется."""
    # С 0.30.130 снятие применяется только при решении о замене, поэтому поставка в фикстуре.
    _trace, receipts = _run(HEADER + WORK + DROP + SUPPLY, monkeypatch, prices=CARPET_PRICES)
    costs = _costs(receipts['lay'])
    assert costs.get('M-PVC', 0) == 0, 'названный материал нормы обязан уйти из денег'
    assert costs['M-GLUE'] > 0, 'остальной состав нормы не трогаем'
    assert costs['L-FIX'] > 0, 'труд нормы не трогаем'


def test_exclusion_is_recorded_as_a_model_decision(monkeypatch):
    """Что именно сняли и по чьему решению — обязано остаться в провенансе.

    С поставкой изделия: снятие без неё по контракту 17.09 — resource_exclusion_unreplaced,
    это проверяет отдельный тест ниже.
    """
    trace, _receipts = _run(HEADER + WORK + DROP + SUPPLY, monkeypatch, prices=CARPET_PRICES)
    drop = next(b for b in trace['row_bindings'] if str(b.get('work_id')) == 'drop')
    assert drop.get('status') == 'resource_excluded'
    binding = (drop.get('resource_bindings') or [{}])[0]
    assert binding.get('action') == 'excluded'
    assert binding.get('resource_code') == 'M-PVC'


def test_project_product_replaces_the_excluded_material_without_double_count(monkeypatch):
    """Снятие плюс самостоятельный материал: покрытие в смете ровно одно."""
    supply = ('| АР!1.31 | supply | Ковровая плитка Atlas 05 | м2 | 100 | — | материал | — '
              '| — | — | M-CARPET | | — | — |\n')
    _trace, receipts = _run(HEADER + WORK + DROP + supply, monkeypatch,
                            prices=PRICES + [dict(code='M-CARPET', unit='м2', price_current=1500)])
    assert _costs(receipts['lay']).get('M-PVC', 0) == 0, 'материал нормы обязан уйти'
    assert _costs(receipts['supply'])['M-CARPET'] > 0, 'проектное изделие обязано попасть в смету'


def test_exclusion_of_a_resource_outside_the_norm_is_refused(monkeypatch):
    """Снять можно только то, что действительно есть в составе этой нормы."""
    bad = ('| АР!1.31 | drop | Нет такого ресурса | м2 | 100 | — | ресурс | lay '
           '| excluded | M-UNKNOWN | — | | — | — |\n')
    trace, receipts = _run(HEADER + WORK + bad, monkeypatch)
    drop = next(b for b in trace['row_bindings'] if str(b.get('work_id')) == 'drop')
    assert drop.get('status') == 'resource_target_missing'
    assert _costs(receipts['lay'])['M-PVC'] > 0, 'отказ не должен молча трогать состав нормы'


def test_receipt_instruction_offers_the_constructive_path():
    """Модель должна узнать, что делать, когда материал нормы — не изделие строки.

    До этого инструкция умела сказать только «это не подтверждение». Теперь есть
    конструктивный путь: снять ресурс нормы и поставить изделие отдельной операцией.
    """
    from proxy.smeta_core.calculation_receipt import receipt_context

    text = receipt_context([{"work_id": "w1", "source_row": "АР!1.31", "calculation_ref": "c" * 64}])
    assert "resource_action=excluded" in text, "инструкция обязана назвать способ снятия"
    assert "target_resource_code" in text, "и то, чем адресуется снимаемый ресурс"


# --- Завершение ресурсной ревизии (аудит Codex 17.09, P1) -------------------------------
# Воспроизведённый дефект .128: пример «работа + снятие ПВХ + покупка ковровой плитки» со
# всеми ценами давал lay=bound, drop=resource_excluded, supply=material_bound, но
# bound_rows=0, unbound_rows=1, full_amount=None, priced_partial и устаревшее сообщение.
# Граница, которую нельзя стирать: исполненное снятие — не учёт строки.

SUPPLY = ('| АР!1.31 | supply | Ковровая плитка Atlas 05 | м2 | 100 | — | материал | — '
          '| — | — | M-CARPET | | — | — |\n')
CARPET_PRICES = PRICES + [dict(code='M-CARPET', unit='м2', price_current=1500)]


def test_fully_priced_revision_with_exclusion_is_final(monkeypatch):
    """Работа, снятие и покупка изделия с ценами — строка учтена полностью."""
    trace, _receipts = _run(HEADER + WORK + DROP + SUPPLY, monkeypatch, prices=CARPET_PRICES)
    summary = trace['summary']
    assert summary['bound_rows'] == 1 and summary['unbound_rows'] == 0, summary
    assert summary['full_amount'] is not None, 'полностью оценённая ревизия не частичная'
    assert summary['result_status'] == 'priced_final'
    drop = next(b for b in trace['row_bindings'] if str(b.get('work_id')) == 'drop')
    assert 'не подтверждён' not in str(drop.get('message') or ''), 'устаревшее сообщение'


def test_exclusion_without_replacement_does_not_account_for_the_row(monkeypatch):
    """Сняли материал нормы и не приняли решения о замене — изделие строки в смете отсутствует."""
    trace, _receipts = _run(HEADER + WORK + DROP_UNLINKED, monkeypatch)
    assert trace['summary']['bound_rows'] == 0
    drop = next(b for b in trace['row_bindings'] if str(b.get('work_id')) == 'drop')
    assert drop.get('status') == 'resource_exclusion_unreplaced', drop


def test_exclusion_alone_never_accounts_for_a_row(monkeypatch):
    """Одно снятие без работы — не учёт исходной строки ни в каком виде."""
    from proxy.smeta_core.row_decision import aggregate_operation_statuses

    statuses = aggregate_operation_statuses([
        {'source_row': 'S!1', 'work_id': 'drop', 'status': 'resource_excluded'}])
    from proxy.smeta_core.row_decision import row_accounted
    assert not row_accounted(statuses['S!1'])


def test_executed_exclusion_does_not_hide_other_operation_failures():
    """Снятие не маскирует проблему соседней операции той же строки."""
    from proxy.smeta_core.row_decision import aggregate_operation_statuses, row_accounted

    statuses = aggregate_operation_statuses([
        {'source_row': 'S!1', 'work_id': 'lay', 'status': 'bound'},
        {'source_row': 'S!1', 'work_id': 'drop', 'status': 'resource_excluded'},
        {'source_row': 'S!1', 'work_id': 'supply', 'status': 'material_price_missing'}])
    assert statuses['S!1'] == 'material_price_missing'
    assert not row_accounted(statuses['S!1'])


def test_repeated_exclusion_of_the_same_resource_is_refused(monkeypatch):
    """Два действия над одним ресурсом нормы неоднозначны — второе отклоняется."""
    again = ('| АР!1.31 | drop2 | Повтор снятия | м2 | 100 | — | ресурс | lay '
             '| excluded | M-PVC | — | | — | — |\n')
    trace, _receipts = _run(HEADER + WORK + DROP + again + SUPPLY, monkeypatch, prices=CARPET_PRICES)
    second = next(b for b in trace['row_bindings'] if str(b.get('work_id')) == 'drop2')
    assert second.get('status') == 'resource_action_conflict', second
    assert trace['summary']['bound_rows'] == 0


def test_inclusion_into_an_excluded_resource_is_refused(monkeypatch):
    """Нельзя одновременно снять ресурс и распределить в него количество."""
    include = ('| АР!1.31 | take | Привязка к снятому ресурсу | м2 | 100 | — | ресурс | lay '
               '| included | M-PVC | — | | — | — |\n')
    trace, _receipts = _run(HEADER + WORK + DROP + include + SUPPLY, monkeypatch, prices=CARPET_PRICES)
    take = next(b for b in trace['row_bindings'] if str(b.get('work_id')) == 'take')
    assert take.get('status') == 'resource_action_conflict', take


def test_changed_composition_produces_a_new_receipt_reference(monkeypatch):
    """Снятие меняет чек работы: подтверждать нужно именно новую ревизию."""
    # Охранный тест существующего свойства: прошёл сразу, поскольку чек и раньше хешировал
    # состав. Он защищает требование аудита «подтверждать именно новый чек».
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda _: dict(NORM))
    from proxy.smeta_core.calculation_receipt import calculation_receipts
    from proxy.services.fgis_price_service import PriceBook

    trace_before = rim.build_lsr_trace_from_visible_rows(
        chat.parse_model_rag_result(HEADER + WORK)[1], pricebook=PriceBook(PRICES))
    trace_after = rim.build_lsr_trace_from_visible_rows(
        chat.parse_model_rag_result(HEADER + WORK + DROP + SUPPLY)[1], pricebook=PriceBook(CARPET_PRICES))
    ref = lambda trace: next(r['calculation_ref'] for r in calculation_receipts(trace, pricebook=None)
                             if str(r['work_id']) == 'lay')
    assert ref(trace_before) != ref(trace_after)


def test_persistence_closes_only_an_accounted_row(tmp_path):
    """Сохранение закрывает строку только при учёте; одно снятие оставляет её открытой."""
    from proxy.services.portion_cursor_service import PortionCursorService
    from proxy.services.chat_evidence_application_service import workbook_row_statuses

    def decided(items):
        store = PortionCursorService(tmp_path / f'{len(items)}.sqlite')
        store.record_pass(session_id='s', source_revision='r', completed={},
                          decisions={'АР!1.31': {'source_row': 'АР!1.31'}}, pass_id='p1')
        statuses = workbook_row_statuses({'workbook_diagnostics': {'row_calculation': items}})
        store.record_calculation(session_id='s', source_revision='r', statuses=statuses)
        return 'АР!1.31' in store.progress(session_id='s', source_revision='r').completed

    full = [{'source_row': 'АР!1.31', 'work_id': 'lay', 'status': 'bound'},
            {'source_row': 'АР!1.31', 'work_id': 'drop', 'status': 'resource_excluded'},
            {'source_row': 'АР!1.31', 'work_id': 'supply', 'status': 'material_bound'}]
    assert decided(full), 'полностью учтённая ревизия закрывает строку'
    assert not decided([full[1]]), 'одно снятие не закрывает строку'


def test_operation_order_does_not_change_the_result(monkeypatch):
    """Снятие раньше работы в таблице модели даёт тот же итог."""
    trace, _receipts = _run(HEADER + DROP + SUPPLY + WORK, monkeypatch, prices=CARPET_PRICES)
    summary = trace['summary']
    assert summary['bound_rows'] == 1 and summary['result_status'] == 'priced_final', summary


def test_workbook_shows_the_exclusion_and_is_not_partial(monkeypatch, tmp_path):
    """Скачанная книга: снятие видно на листе проверки, расчёт не помечен незавершённым."""
    import openpyxl
    from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx

    trace, _receipts = _run(HEADER + WORK + DROP + SUPPLY, monkeypatch, prices=CARPET_PRICES)
    out = tmp_path / 'excluded.xlsx'
    render_lsr_xlsx(trace, out)
    workbook = openpyxl.load_workbook(out)
    try:
        cells = [str(c) for sheet in workbook.worksheets
                 for row in sheet.iter_rows(values_only=True) for c in row if c is not None]
    finally:
        workbook.close()
    text = '\n'.join(cells)
    assert 'M-CARPET' in text or 'Ковровая плитка' in text, 'изделие видно в книге'
    assert 'РАСЧЁТ НЕ ЗАВЕРШЁН' not in text, 'полная ревизия не маркируется как незавершённая'


# --- Проверка 0.30.129 Codex 17.09: цена снятого ресурса и явная связь замены ------------
# Воспроизведено: без цены исключённого ПВХ итог оставался частичным («нужен КАЦ» на ненужный
# ресурс); поставка 0 м² вместо снятых 102 м² давала priced_final; одна поставка «заменяла»
# сразу ПВХ и клей; обоснованное снятие без покупки (демонтаж) было невозможно.

def _binding(trace, work_id):
    return next(b for b in trace['row_bindings'] if str(b.get('work_id')) == work_id)


def test_excluded_material_without_price_does_not_require_one(monkeypatch):
    """Цена снятого ресурса не нужна: он не участвует в деньгах."""
    prices = [p for p in CARPET_PRICES if p['code'] != 'M-PVC']
    trace, _receipts = _run(HEADER + WORK + DROP + SUPPLY, monkeypatch, prices=prices)
    summary = trace['summary']
    assert summary['result_status'] == 'priced_final', summary
    assert not any('M-PVC' in str(flag) for flag in summary.get('flags') or []), summary.get('flags')


def test_price_is_still_required_for_a_resource_that_was_not_excluded(monkeypatch):
    """Пропуск цены — только для исполненного снятия, а не для любого ресурса."""
    prices = [p for p in CARPET_PRICES if p['code'] != 'M-GLUE']
    trace, _receipts = _run(HEADER + WORK + DROP + SUPPLY, monkeypatch, prices=prices)
    assert trace['summary']['result_status'] == 'priced_partial'
    assert any('M-GLUE' in str(flag) for flag in trace['summary'].get('flags') or [])


def test_zero_quantity_replacement_is_refused(monkeypatch):
    """Поставка 0 м² не заменяет снятые 102 м²: связь есть, количества нет."""
    zero = SUPPLY.replace('| м2 | 100 |', '| м2 | 0 |')
    trace, receipts = _run(HEADER + WORK + DROP + zero, monkeypatch, prices=CARPET_PRICES)
    assert _binding(trace, 'drop')['status'] == 'resource_exclusion_replacement_invalid'
    assert trace['summary']['result_status'] != 'priced_final'
    assert _costs(receipts['lay'])['M-PVC'] > 0, 'отклонённое снятие не меняет состав нормы'


def test_one_supply_cannot_replace_two_excluded_resources(monkeypatch):
    """Одна поставка — замена одного снятого ресурса, иначе замена не проверяема."""
    glue = ('| АР!1.31 | drop_glue | Клей не применяется | кг | 52 | — | ресурс | lay '
            '| excluded | M-GLUE | — | | supply | — |\n')
    trace, _receipts = _run(HEADER + WORK + DROP + glue + SUPPLY, monkeypatch, prices=CARPET_PRICES)
    statuses = {_binding(trace, 'drop')['status'], _binding(trace, 'drop_glue')['status']}
    assert 'resource_exclusion_replacement_invalid' in statuses, statuses
    assert trace['summary']['result_status'] != 'priced_final'


def test_replacement_must_be_a_material_supply_of_the_same_row(monkeypatch):
    """Ссылка на работу или на несуществующую операцию — не замена."""
    for target in ('lay', 'nosuch'):
        drop = DROP.replace('| supply | — |', f'| {target} | — |')
        trace, _receipts = _run(HEADER + WORK + drop + SUPPLY, monkeypatch, prices=CARPET_PRICES)
        assert _binding(trace, 'drop')['status'] == 'resource_exclusion_replacement_invalid', target
        assert trace['summary']['result_status'] != 'priced_final'


def test_unneeded_material_can_be_excluded_with_a_justification(monkeypatch):
    """Обоснованное отсутствие потребности — законное решение модели без новой покупки."""
    drop = DROP.replace('| supply | — |', '| not_required | демонтаж: новая плитка не укладывается |')
    trace, receipts = _run(HEADER + WORK + drop, monkeypatch)
    assert _binding(trace, 'drop')['status'] == 'resource_excluded'
    assert _costs(receipts['lay']).get('M-PVC', 0) == 0
    assert trace['summary']['result_status'] == 'priced_final'


def test_not_required_without_a_justification_is_refused(monkeypatch):
    drop = DROP.replace('| supply | — |', '| not_required | — |')
    trace, receipts = _run(HEADER + WORK + drop, monkeypatch)
    assert _binding(trace, 'drop')['status'] == 'resource_exclusion_unjustified'
    assert trace['summary']['result_status'] != 'priced_final'
    assert _costs(receipts['lay'])['M-PVC'] > 0, 'необоснованное снятие не меняет состав нормы'


def test_exclusion_without_a_decision_leaves_the_norm_composition_intact(monkeypatch):
    """Пока решения о замене нет, деньги нормы не уменьшаются молча."""
    trace, receipts = _run(HEADER + WORK + DROP_UNLINKED, monkeypatch)
    assert _binding(trace, 'drop')['status'] == 'resource_exclusion_unreplaced'
    assert _costs(receipts['lay'])['M-PVC'] > 0


def test_replacement_provenance_shows_both_quantities(monkeypatch):
    """Снятое и поставленное количество видны рядом — их соотношение проверяет приёмка."""
    trace, _receipts = _run(HEADER + WORK + DROP + SUPPLY, monkeypatch, prices=CARPET_PRICES)
    item = (_binding(trace, 'drop').get('resource_bindings') or [{}])[0]
    assert item.get('excluded_quantity') == 102 and item.get('excluded_unit') == 'м2', item
    assert item.get('replaced_by') == 'supply'
    assert item.get('replacement_quantity') == 100 and item.get('replacement_unit') == 'м2', item



def test_instructions_name_the_replacement_link_and_the_justified_absence():
    """Модель должна знать, как связать замену и как обосновать отсутствие потребности."""
    from proxy.smeta_core.calculation_receipt import receipt_context
    from proxy.services.chat_evidence_application_service import model_answer_request

    receipt = receipt_context([{"work_id": "w1", "source_row": "АР!1.31", "calculation_ref": "c" * 64}])
    assert 'replaced_by' in receipt and 'not_required' in receipt
    assert 'replaced_by' in model_answer_request('Смета', model_driven=True)


# --- Снятие машин (решение 17.09): только not_required с обоснованием; труд не снимается ----
# АР!1.31: у ковровой плитки остались «Машины мозаично-шлифовальные», хотя модель сама
# написала «шлифовка не нужна». Машину нельзя заменить поставкой материала, а труд — ядро
# нормы: если он не подходит, модель выбирает другую норму.

NORM_WITH_MACHINE = dict(NORM, resources=NORM['resources'] + [
    dict(kind='machine', code='M-GRIND', name='Машины мозаично-шлифовальные', unit='маш.-ч', per_unit=9)])
MACHINE_PRICES = CARPET_PRICES + [dict(code='M-GRIND', unit='маш.-ч', price_current=20)]


def _run_machine(raw, monkeypatch):
    from proxy.services.fgis_price_service import PriceBook
    from proxy.smeta_core.calculation_receipt import calculation_receipts

    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda _: dict(NORM_WITH_MACHINE))
    pricebook = PriceBook(MACHINE_PRICES)
    rows = chat.parse_model_rag_result(raw)[1]
    trace = rim.build_lsr_trace_from_visible_rows(rows, pricebook=pricebook)
    receipts = {str(item['work_id']): (item.get('calculation') or {})
                for item in calculation_receipts(trace, pricebook=pricebook)}
    return trace, receipts


def _drop_row(work_id, code, link, reason='—'):
    return (f'| АР!1.31 | {work_id} | Снять {code} | м2 | 100 | — | ресурс | lay '
            f'| excluded | {code} | — | | {link} | {reason} |\n')


def test_unneeded_machine_can_be_excluded_with_a_justification(monkeypatch):
    raw = HEADER + WORK + DROP + SUPPLY + _drop_row('drop_grind', 'M-GRIND', 'not_required',
                                                    'шлифовка основания для ковровой плитки не выполняется')
    trace, receipts = _run_machine(raw, monkeypatch)
    assert _binding(trace, 'drop_grind')['status'] == 'resource_excluded'
    costs = _costs(receipts['lay'])
    assert costs.get('M-GRIND', 0) == 0 and costs['L-FIX'] > 0 and costs['M-GLUE'] > 0
    assert trace['summary']['result_status'] == 'priced_final', trace['summary']


def test_machine_cannot_be_replaced_by_a_material_supply(monkeypatch):
    raw = HEADER + WORK + DROP_UNLINKED + SUPPLY + _drop_row('drop_grind', 'M-GRIND', 'supply')
    trace, receipts = _run_machine(raw, monkeypatch)
    assert _binding(trace, 'drop_grind')['status'] == 'resource_exclusion_replacement_invalid'
    assert _costs(receipts['lay'])['M-GRIND'] > 0


def test_labor_of_the_norm_is_not_excludable(monkeypatch):
    raw = HEADER + WORK + DROP + SUPPLY + _drop_row('drop_labor', 'L-FIX', 'not_required', 'не нужно')
    trace, receipts = _run_machine(raw, monkeypatch)
    assert _binding(trace, 'drop_labor')['status'] == 'resource_action_not_allowed'
    assert _costs(receipts['lay'])['L-FIX'] > 0
    assert trace['summary']['result_status'] != 'priced_final'


def test_excluded_machine_removes_its_crew_hours_from_the_machinist_aggregate(monkeypatch):
    """Часы машинистов снятой машины уходят вместе с ней, сверка ФСЭМ не рвётся."""
    from proxy.services import fsem_machinist_service as fsem

    crews = {'MACH-A': dict(crew_hours=1, driver_code='4-100-040', driver_grade=4),
             'MACH-B': dict(crew_hours=1, driver_code='4-100-030', driver_grade=3)}
    monkeypatch.setattr(fsem, 'lookup', lambda code, *_a, **_k: crews.get(code))
    resources = [
        dict(kind='machine', code='MACH-A', name='A', unit='маш.-ч', per_unit=0,
             excluded=True, excluded_per_unit=2),
        dict(kind='machine', code='MACH-B', name='B', unit='маш.-ч', per_unit=1),
        dict(kind='machinist', code='', name='Затраты труда машинистов', unit='чел.-ч', per_unit=3),
    ]
    enriched, trace = fsem.enrich_machinists(resources, quantity_field='per_unit')
    assert trace['status'] == 'reconciled', trace
    machinists = [r for r in enriched if r['kind'] == 'machinist']
    assert [(r['code'], r['per_unit']) for r in machinists] == [('4-100-030', 1.0)]
