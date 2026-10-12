"""Подтверждение расчёта не закрывает строку, по которой модель сама объявила непокрытие.

`keep_all_confirmed` — это один ответ на весь расчёт, и до сих пор он молча проставлял
«подтверждено» всем трём компонентам: труду, машинам и материалам. Живой прогон большой
ВОР 14–15.09: из шести закрытых строк ПЯТЬ несли собственное `not_covered`, а
покомпонентный статус модель не заполнила ни разу — 0 из 198 строк. Так закрылась
АР!1.31 «Ковровая плитка Atlas 05» по норме на ПВХ-плитки с её же пометкой
«not_covered: материал ковровая плитка vs ПВХ».

Код не выбирает норму за модель и не объявляет её негодной. Он отказывается считать
расчёт подтверждённым, пока подтверждение противоречит собственной пометке автора.
Снять отказ модель может сама — явным `material_review_status` с обоснованием.
"""

from __future__ import annotations

import pytest

from proxy.smeta_core.calculation_receipt import apply_model_review, calculation_receipts
from proxy.services.rim_lsr_trace_service import build_lsr_trace


def _trace_and_receipts():
    trace = build_lsr_trace([dict(code='ГЭСН11-01-038-02', name='Устройство покрытий из плиток поливинилхлоридных',
                                  source_row='АР!1.31', work_id='w1', unit='м2', qty=66.7,
                                  nr_pct=0, sp_pct=0, resources=[])])
    trace['row_bindings'] = [dict(row='АР!1.31', work_id='w1', status='bound')]
    trace['summary'].update(source_rows=1, bound_rows=1, bound_operations=1,
                            unbound_rows=0, unbound_operations=0)
    return trace, calculation_receipts(trace)


def _decision(**extra):
    trace, receipts = _trace_and_receipts()
    row = dict(source_row='АР!1.31', work_id='w1',
               resource_review_status='keep_all_confirmed',
               resource_review_ref=receipts[0]['calculation_ref'])
    row.update(extra)
    apply_model_review(trace, receipts, [row])
    return trace


def test_blanket_confirmation_does_not_close_a_row_with_declared_non_coverage():
    """Пометка «не покрыто» и общее подтверждение в одной строке — не подтверждение."""
    trace = _decision(coverage='not_covered: материал ковровая плитка vs ПВХ; клей КН-2 vs неизвестный')
    binding = trace['row_bindings'][0]
    assert binding['status'] == 'resource_review_required', (
        'строка с собственным not_covered не должна закрываться общим keep_all_confirmed')


def test_declared_non_coverage_in_its_own_field_is_honoured_too():
    """Поле `not_covered` — то же самое утверждение, что и префикс внутри coverage."""
    trace = _decision(coverage='Устройство покрытий из плиток на клее',
                      not_covered='материал ковровая плитка vs ПВХ')
    assert trace['row_bindings'][0]['status'] == 'resource_review_required'


def test_model_can_clear_the_gate_with_an_explicit_material_review():
    """Отказ снимает сама модель: явный статус материала с обоснованием."""
    trace = _decision(coverage='not_covered: материал ковровая плитка vs ПВХ',
                      material_review_status='confirmed',
                      material_review_reason='ковровая плитка 500х500 укладывается на клей как плиточное покрытие')
    assert trace['row_bindings'][0]['status'] == 'bound', (
        'явное покомпонентное решение модели остаётся её решением и закрывает строку')


@pytest.mark.parametrize('status', ['not_present', 'unresolved', 'rejected'])
def test_material_review_other_than_confirmed_keeps_the_row_open(status):
    trace = _decision(coverage='not_covered: материал ковровая плитка vs ПВХ',
                      material_review_status=status, material_review_reason='проверено')
    assert trace['row_bindings'][0]['status'] == 'resource_review_required'


def test_row_without_declared_non_coverage_still_closes_as_before():
    """Регресс-защита: обычное подтверждение без пометок работает как раньше."""
    trace = _decision(coverage='Окраска за 2 раза, подготовка поверхности')
    assert trace['row_bindings'][0]['status'] == 'bound'


def test_reader_accepts_the_component_review_columns():
    """Путь снятия отказа обязан быть достижим: колонки должны доходить до кода.

    Читатель принимает только перечисленные имена колонок, остальные молча выбрасывает.
    Без этих двух модель физически не может сообщить явное решение по материалу, и гейт
    из тестов выше стал бы глухой заглушкой.
    """
    from proxy.services.chat_evidence_application_service import parse_model_rag_result

    answer = (
        "| source_row | section | title | unit | quantity | norm_code | analogue | coverage "
        "| coefficient | evidence_refs | material_review_status | material_review_reason |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| АР!1.31 | Полы | Ковровая плитка Atlas 05 | м2 | 66.7 | ГЭСН11-01-038-02 "
        "| Устройство покрытий из плиток поливинилхлоридных | not_covered: материал ковровая плитка vs ПВХ "
        "| 1 | Q1.H1 | confirmed | плитка 500х500 на клею, укладка как у плиточного покрытия |\n"
    )
    parsed = parse_model_rag_result(answer)
    assert parsed is not None, "таблица должна разбираться"
    _text, rows = parsed
    row = next(item for item in rows if str(item.get("source_row")) == "АР!1.31")
    assert row.get("material_review_status") == "confirmed"
    assert "плитка 500х500" in str(row.get("material_review_reason") or "")


def test_receipt_instruction_states_what_confirmation_costs():
    """Модель обязана знать цену подтверждения: материалы нормы остаются в смете.

    АР!1.31 «Ковровая плитка Atlas 05» закрылась подтверждением, оставив в расчёте
    «Плитка ПВХ для полов, толщина 1,2 мм» — 68,034 м² по 318,23 ₽ базы, 26 197,17 ₽
    из 108 223,97 ₽ позиции. Это не открытая позиция без цены, а уверенные деньги за
    другой товар. Подстановки материала в активном контуре нет: единственное
    `resource_action` — `included`, то есть привязка, а не замена.
    """
    from proxy.smeta_core.calculation_receipt import receipt_context

    text = receipt_context([{"work_id": "w1", "source_row": "АР!1.31", "calculation_ref": "c" * 64}])
    assert "остаются в смете" in text or "остаётся в смете" in text, (
        "инструкция обязана называть последствие подтверждения")
    # В 0.30.127 здесь проверялось, что инструкция ЗАПРЕЩАЕТ подтверждение чужого товара,
    # потому что снять материал нормы было нечем. В 0.30.128 снятие появилось
    # (resource_action=excluded), и инструкция обязана вести к нему, а не в тупик.
    assert "дважды" in text, "инструкция обязана предупредить о двойном учёте"
