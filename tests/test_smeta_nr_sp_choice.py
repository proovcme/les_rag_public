"""Модель выбирает норматив НР/СП, код проверяет выбор по каталогу Приказов 812/пр и 774/пр.

ЗАЧЕМ. Живая проверка 17.09, СКС!5.6: работа ГЭСНм10-01-055-02 посчитана, но полной суммы
нет — «НР/СП не разрешены по виду работ». Для сборника ГЭСНм10 в каталоге пять нормативов
(сети связи, радиоэлектроника, междугородные линии, железные дороги, аэродромы), и код
сознательно не выбирает между ними по названию. Но в чатовом сметном пути у модели не было
ни колонки для выбора, ни списка вариантов: любая монтажная норма оставалась без НР/СП навсегда.

ЧТО ЗДЕСЬ. Чек расчёта показывает варианты; модель возвращает `nr_sp_rule_id`; расчёт берёт
проценты только из выбранного правила каталога, чужое правило отвергается. Выбор норматива —
решение модели, а не пересмотр расчёта: `calculation_ref` от него не меняется, и лишний проход
подтверждения не нужен.
"""
from proxy.services import chat_evidence_application_service as chat
from proxy.services import rim_lsr_trace_service as rim

NORM = {
    'name': 'Прокладка кабеля, масса 1 м: до 1 кг, по стене кирпичной', 'unit': '100 м',
    'resources': [dict(kind='labor', code='1-100-35', name='Средний разряд работы 3,5', unit='чел.-ч', per_unit=34)],
}
PRICES = [dict(code='1-100-35', unit='чел.-ч', price_current=700)]
HEADER = ('| source_row | work_id | title | unit | quantity | norm_code | nr_sp_rule_id | evidence_refs |\n'
          '|---|---|---|---|---|---|---|---|\n')


def _run(monkeypatch, rule=''):
    from proxy.services.fgis_price_service import PriceBook
    from proxy.smeta_core.calculation_receipt import calculation_receipts

    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda _: dict(NORM))
    raw = HEADER + f'| СКС!5.6 | lay | Прокладка витой пары | м | 8500 | ГЭСНм10-01-055-02 | {rule or "—"} | Q1.H1 |\n'
    rows = chat.parse_model_rag_result(raw)[1]
    pricebook = PriceBook(PRICES)
    trace = rim.build_lsr_trace_from_visible_rows(rows, pricebook=pricebook)
    receipt = calculation_receipts(trace, pricebook=pricebook)[0]
    summary = trace['sections'][0]['positions'][0]['summary']
    return summary, receipt


def test_receipt_shows_the_catalog_choices_when_the_collection_is_ambiguous(monkeypatch):
    summary, receipt = _run(monkeypatch)
    assert 'nr_sp_unresolved' in summary['completeness_reasons']
    nr_sp = receipt['calculation']['nr_sp']
    assert nr_sp['status'] == 'ambiguous'
    choice = next(item for item in nr_sp['candidates'] if item['rule_id'] == 'nrsp-51.1')
    assert 'сетей связи' in choice['label'] and choice['nr_pct'] == 90.0 and choice['sp_pct'] == 46.0


def test_model_choice_resolves_overheads_from_the_catalog(monkeypatch):
    summary, receipt = _run(monkeypatch, 'nrsp-51.1')
    assert summary['nr_pct'] == 90.0 and summary['sp_pct'] == 46.0
    assert 'nr_sp_unresolved' not in summary['completeness_reasons']
    assert summary['nr'] > 0 and summary['sp'] > 0
    assert receipt['calculation']['nr_sp']['status'] == 'resolved_explicit'
    assert receipt['calculation']['nr_sp']['rule_id'] == 'nrsp-51.1'


def test_rule_of_another_collection_is_rejected(monkeypatch):
    summary, receipt = _run(monkeypatch, 'nrsp-49.3')
    assert 'nr_sp_unresolved' in summary['completeness_reasons']
    assert receipt['calculation']['nr_sp']['status'] == 'rejected'


def test_choosing_overheads_does_not_reopen_the_confirmed_calculation(monkeypatch):
    _summary, before = _run(monkeypatch)
    _summary, after = _run(monkeypatch, 'nrsp-51.1')
    assert before['calculation_ref'] == after['calculation_ref']


def test_instructions_name_the_overhead_choice_column():
    from proxy.smeta_core.calculation_receipt import receipt_context

    assert 'nr_sp_rule_id' in receipt_context([{'work_id': 'x'}])
    assert 'nr_sp_rule_id' in chat.model_answer_request('Смета', model_driven=True)


def test_overhead_choice_survives_the_portion_cursor():
    from proxy.services.portion_cursor_service import DECISION_FIELDS

    assert 'nr_sp_rule_id' in DECISION_FIELDS


def test_iq2_m_answer_model_gets_the_same_verified_launch_profile():
    """17.09 роль ответа переведена на UD-IQ2_M: без профиля она стартовала бы без ctx_size и
    с несколькими слотами KV-кэша, и 22 тыс. входа сметного запроса не поместились бы."""
    from extensions.lemonade.model_policy import recommended_recipe_options

    options = recommended_recipe_options("Qwen3.6-35B-A3B-GGUF-UD-IQ2_M")
    assert options == recommended_recipe_options("Qwen3.6-35B-A3B-GGUF-UD-IQ2_XXS-unsloth")
    assert options["ctx_size"] == 32768 and "--parallel 1" in options["llamacpp_args"]
