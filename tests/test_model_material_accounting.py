from copy import deepcopy

from proxy.services import rim_lsr_trace_service as rim
from proxy.services.fgis_price_service import PriceBook

CODE = 'ГЭСНм08-02-395-01'


def setup_norm(monkeypatch):
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda code: {
        'name': 'Монтаж', 'unit': 'шт', 'resources': [
            {'kind': 'material', 'code': '01.1.01.01-0001', 'name': 'Крепёж', 'unit': 'шт', 'per_unit': 4},
        ],
    })


def work():
    return dict(source_row='S!1', title='Монтаж', norm_code=CODE, quantity=2, unit='шт')


def included(**kw):
    return dict(source_row='S!2', title='Крепёж', norm_code='', quantity=8, unit='шт',
                decision_kind='ресурс', included_in='S!1', resource_action='included',
                target_resource_code='01.1.01.01-0001', coverage='Количество в ресурсе нормы', **kw)


def test_explicit_resource_link_is_verified_without_second_work(monkeypatch):
    setup_norm(monkeypatch)
    rows = [work(), included()]
    original = deepcopy(rows)
    result = rim.positions_from_visible_lsr_rows(rows)
    assert rows == original
    assert len(result['positions']) == 1
    binding = result['row_bindings'][1]
    assert binding['status'] == 'resource_bound'
    assert binding['covered_by_work_id'] == 'S!1'
    assert binding['resource_bindings'][0]['quantity'] == 8


def test_same_resource_quantity_cannot_cover_two_rows(monkeypatch):
    setup_norm(monkeypatch)
    second = dict(included(), source_row='S!3')
    result = rim.positions_from_visible_lsr_rows([work(), included(), second])
    assert result['row_bindings'][1]['status'] == 'resource_bound'
    assert result['row_bindings'][2]['status'] == 'resource_quantity_exceeded'


def test_parent_norm_code_does_not_choose_between_work_positions(monkeypatch):
    setup_norm(monkeypatch)
    resource = dict(included(), included_in=CODE)
    result = rim.positions_from_visible_lsr_rows([work(), dict(work(), source_row='S!3'), resource])
    assert result['row_bindings'][-1]['status'] == 'resource_parent_ambiguous'


def test_standalone_material_uses_exact_price_code(monkeypatch):
    setup_norm(monkeypatch)
    row = dict(source_row='S!1', decision_kind='материал', title='Крепёж', quantity=3, unit='шт',
               resource_code='01.1.01.01-0001', norm_code='')
    prices = PriceBook([dict(code=row['resource_code'], name='Крепёж', unit='шт', price_current_eff=12)])
    result = rim.build_lsr_trace_from_visible_rows([row], pricebook=prices)
    assert result['row_bindings'][0]['status'] == 'material_bound'
    position = result['sections'][0]['positions'][0]
    assert position['summary']['mat'] == 36
    assert position['summary']['ozp'] == 0
    assert position['summary']['nr'] == 0


def test_material_without_price_still_remains_in_output(monkeypatch):
    setup_norm(monkeypatch)
    row = dict(source_row='S!1', decision_kind='материал', title='Крепёж', quantity=3, unit='шт', norm_code='')
    result = rim.positions_from_visible_lsr_rows([row])
    assert len(result['positions']) == 1
    assert result['row_bindings'][0]['status'] == 'material_price_missing'


def test_resource_fields_change_revision_and_survive_parser():
    from proxy.services.chat_evidence_application_service import parse_model_rag_result
    from proxy.services.portion_cursor_service import decisions_revision
    raw = '| source_row | title | unit | quantity | norm_code | decision_kind | included_in | resource_action | target_resource_code |\n|---|---|---|---|---|---|---|---|---|\n| S!2 | Крепёж | шт | 8 | — | ресурс | S!1 | included | 01.1.01.01-0001 |'
    rows = parse_model_rag_result(raw)[1]
    assert rows[0]['target_resource_code'] == '01.1.01.01-0001'
    assert decisions_revision(rows) != decisions_revision([dict(rows[0], target_resource_code='other')])


def test_resource_cards_expose_exact_resource_identifiers():
    from proxy.services.model_research_tool_service import smeta_card_text
    card = dict(norm_code='', title='Работа', resource_preview=[
        dict(kind='material', code='01.1.01.01-0001', name='Крепёж', unit='шт')])
    text = smeta_card_text(card)
    assert '01.1.01.01-0001' in text
    assert 'Крепёж' in text


def test_accounted_source_rows_are_not_counted_as_work_positions(monkeypatch):
    setup_norm(monkeypatch)
    trace = rim.build_lsr_trace_from_visible_rows([work(), included()])
    assert trace['summary']['bound_rows'] == 2
    assert trace['summary']['work_positions'] == 1


def test_material_price_unit_conflict_does_not_create_fake_cost(monkeypatch):
    setup_norm(monkeypatch)
    row = dict(source_row='S!1', decision_kind='материал', title='Крепёж', quantity=3, unit='шт',
               resource_code='01.1.01.01-0001', norm_code='')
    prices = PriceBook([dict(code=row['resource_code'], name='Крепёж', unit='т', price_current_eff=100000)])
    trace = rim.build_lsr_trace_from_visible_rows([row], pricebook=prices)
    assert trace['row_bindings'][0]['status'] == 'material_price_unit_conflict'
    assert trace['sections'][0]['positions'][0]['summary']['mat'] == 0


def test_documented_mass_conversion_preserves_quantity_provenance():
    row = dict(quantity=6, unit='м.п.', conversion_factor=3.03, conversion_unit='кг',
               conversion_source='https://www.dkc.ru/ru/catalog/10/fc5050/')
    quantity, trace = rim._norm_qty_from_visible_row(row, CODE, {'unit': 'т'})
    assert abs(quantity - 0.01818) < 1e-9
    assert trace['conversion_source'] == row['conversion_source']
    assert trace['source_quantity'] == 6
    assert trace['source_unit'] == 'м.п.'


def test_conversion_without_source_is_not_applied():
    row = dict(quantity=6, unit='м', conversion_factor=3.03, conversion_unit='кг')
    quantity, trace = rim._norm_qty_from_visible_row(row, CODE, {'unit': 'т'})
    assert quantity is None


def test_article_suffix_does_not_supply_package_count():
    row = dict(quantity=2, unit='упак.', title='PLEZ-8P8C-U-C5-100')
    quantity, _ = rim._norm_qty_from_visible_row(row, CODE, {'unit': '100 шт'})
    assert quantity is None


def test_conversion_source_reaches_xlsx_quantity_cell(tmp_path, monkeypatch):
    import openpyxl
    from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
    setup_norm(monkeypatch)
    position = dict(code=CODE, name='Лоток', unit='т', qty=0.01818,
                    source_row='S!1038', resources=[],
                    quantity_trace=dict(formula='6 м × 3.03 кг/м / 1000',
                                        conversion_source='https://www.dkc.ru/ru/catalog/10/fc5050/'))
    trace = rim.build_lsr_trace([position])
    path = tmp_path / 'trace.xlsx'
    render_lsr_xlsx(trace, path)
    book = openpyxl.load_workbook(path)
    try:
        row = next(row for row in book.worksheets[0] if row[1].value == CODE)
        assert row[4].comment is not None
        assert 'https://www.dkc.ru/ru/catalog/10/fc5050/' in row[4].comment.text
        assert 'S!1038' in row[1].comment.text
    finally:
        book.close()


# --- Проход 27: явный отказ от поставки при демонтаже ---------------------------------------
# Модель ответила ровно то, чего от неё ждали: «Демонтаж; изделие не поставляется»,
# material_review_status=not_present и без resource_code. Расчёт назвал это материалом без
# цены и держал строку открытой, хотя поставки нет и цена не нужна.

def _supply_binding(review_status, code=''):
    from proxy.smeta_core.material_accounting import account_material_rows

    bindings = [{
        'status': 'material_pricing_required',
        'work_id': 'СОУЭ!7.2-2',
        'row': 'СОУЭ!7.2',
        'source_row': {'source_row': 'СОУЭ!7.2', 'title': 'Поставка оповещателя', 'unit': 'шт',
                       'quantity': 7, 'resource_code': code,
                       'material_review_status': review_status,
                       'material_review_reason': 'Демонтаж; изделие не поставляется'},
    }]
    account_material_rows([], bindings, pricebook=None)
    return bindings[0]


def test_supply_declared_absent_is_executed_not_priced():
    assert _supply_binding('not_present')['status'] == 'material_not_supplied'
    # Без такого решения пробел в цене остаётся пробелом.
    assert _supply_binding('')['status'] == 'material_price_missing'
    # Названный код — это заявка на поставку: отказ не читается.
    assert _supply_binding('not_present', code='61.2.04.05-0004')['status'] == 'material_price_missing'


def test_absent_supply_does_not_account_for_the_row_but_does_not_block_it():
    from proxy.smeta_core.row_decision import operation_executed, row_accounted

    assert operation_executed('material_not_supplied')
    assert not row_accounted('material_not_supplied')


def test_supply_marked_not_required_is_executed_even_with_a_code():
    """Проход 30: модель выполнила то, что просит контракт, а код это не исполнил.

    По строке демонтажа она вернула replaced_by=not_required, material_review_status=
    rejected и причину «row_work_is_removal: демонтаж; изделие не поставляется», оставив
    код изделия из карточки. Отказ от поставки назван явно — считать его заявкой на
    поставку и ждать цену незачем.
    """
    from proxy.smeta_core.material_accounting import account_material_rows

    bindings = [{
        'status': 'material_pricing_required',
        'work_id': 'СОУЭ!7.2-2',
        'row': 'СОУЭ!7.2',
        'source_row': {'source_row': 'СОУЭ!7.2', 'title': 'Поставка оповещателя', 'unit': 'шт',
                       'quantity': 7, 'resource_code': '61.2.04.05-0004',
                       'replaced_by': 'not_required',
                       'material_review_status': 'rejected',
                       'material_review_reason': 'row_work_is_removal: демонтаж; изделие не поставляется'},
    }]
    account_material_rows([], bindings, pricebook=None)
    assert bindings[0]['status'] == 'material_not_supplied'
