"""Smeta chat channel: only code-based quick tools, never object compositions."""

from __future__ import annotations

from proxy.services import fgis_price_service as fps
from proxy.services.smeta_chat_service import _fmt_num, maybe_handle_smeta_query as h
from tests.lsr_gold_pricebook import gold_pricebook  # noqa: F401  (фикстура по имени)


def test_price_routes_even_without_book(monkeypatch):
    monkeypatch.setattr(fps, "available_pricebooks", lambda *a, **k: [])
    r = h("цена 91.05.01-017")
    assert r is not None and r["operation"] == "price"
    assert "книг" in r["answer"].lower()


def test_needs_kac_route():
    r = h("нужен ли КАЦ для 99.99.99-999")
    assert r is not None and r["operation"] == "needs_kac"


def test_stesnennost_route():
    # Код не выбирает применимость коэффициента из короткой фразы.
    assert h("коэффициент стеснённости для города") is None
    assert h("какой коэффициент стеснённости") is None


def test_code_extraction():
    from proxy.services.smeta_chat_service import _first_code

    assert _first_code("цена 91.05.01-017 пожалуйста") == "91.05.01-017"
    assert _first_code("сколько стоит 01.7.15.06-0111") == "01.7.15.06-0111"
    assert _first_code("нет кода тут") is None


def test_assemble_from_code_reproduces_gold_position(gold_pricebook):
    """Сумма быстрых «собери …» закреплены за книгой эталона, а не за машиной оператора.

    Разбор итога — в ``tests/test_rim_lsr_trace_service.py`` (``GOLD_*``): ОЗП 4 006,37 +
    ЭМ 1 130,59 + М 78,47 = прямые 5 215,43, НР 4 901,04 + СП 2 562,93 → 12 679,40.
    Строка 11.1.03.01-0076 в книге эталона отсутствует намеренно, и канал обязан назвать
    этот вопрос, а не закрыть его молча.
    """
    r = h("собери ГЭСН12-01-034-02 объём 61 м2")
    assert r is not None and r["operation"] == "assemble"
    assert "12 679.40" in r["answer"]
    assert "ОЗП 4 006.37" in r["answer"]
    assert "11.1.03.01-0076" in r["answer"]
    assert r["calculation_status"] == "partial"


def test_assemble_does_not_guess_stesnennost_from_phrase(gold_pricebook):
    r = h("собери ГЭСН12-01-034-02 объём 61 м2 стеснённость город")
    assert r["operation"] == "assemble"
    # стеснённость из короткой фразы не применяется: деньги остаются деньгами книги
    assert "12 679.40" in r["answer"]
    assert "14 569.55" not in r["answer"]  # та же позиция с осознанным k=1,15


def test_assemble_needs_volume():
    r = h("собери ГЭСН12-01-034-02")
    assert r["operation"] == "assemble" and "объём" in r["answer"].lower()


def test_assemble_separates_the_named_volume_from_the_card_unit(gold_pricebook):
    """«61» — физический объём оператора в м2, а не 61 карточка по 100 м2.

    До сборки 830 строка печатала «объём 61.0 100 м2»: деньги при этом считались от 0,61
    карточки, поэтому строка противоречила собственной трассе и предлагала оператору
    прочитать итог в 100 раз неверно.  Теперь названы обе меры.
    """
    r = h("собери ГЭСН12-01-034-02 объём 61 м2")
    line = next(row for row in r["answer"].splitlines() if "объём" in row)

    assert "61.0 м2" in line
    assert "карточка нормы — на 100 м2" in line
    assert "61.0 100 м2" not in line


def test_partial_position_is_not_named_a_total_in_chat(gold_pricebook):
    """Чат подписывает незакрытую позицию теми же словами, что и доставленная форма.

    `rim_lsr_trace_service` пишет «Всего по позиции» только при закрытом `full_amount`, а
    иначе — «Известная стоимость позиции».  Канал до 830 печатал «ИТОГО по позиции» в обоих
    случаях, то есть называл итогом то же самое число, которое строкой ниже помечало себя
    пробелом `11.1.03.01-0076`.
    """
    r = h("собери ГЭСН12-01-034-02 объём 61 м2")

    assert r["calculation_status"] == "partial"
    assert "Известная стоимость позиции: 12 679.40 руб." in r["answer"]
    assert "ИТОГО по позиции" not in r["answer"]
    assert "Всего по позиции" not in r["answer"]


def test_chat_never_promises_recheck_free_numbers_over_a_partial_position(gold_pricebook):
    """Ни одна достижимая формулировка сборки не обещает «не перепроверять» над `partial`.

    Замер до правки: 20 из 28 достижимых формулировок (`_ASSEMBLE_WORDS` × объём) давали
    рамку «Готово, цифры выверены — можешь не перепроверять:» над позицией, у которой
    `calculation_status == "partial"`.  Проверка идёт по всем формулировкам, потому что
    выбор рамки — хэш от запроса: один вариант был бы случайностью, а не свойством.
    """
    phrasings = [
        f"{word} ГЭСН12-01-034-02 {volume}"
        for word in ("собери", "собрать", "посчитай смет", "посчитай позиц", "смета по",
                     "сосчитай", "рассчитай смет")
        for volume in ("объём 61 м2", "объём 0,61", "объём 100", "61 м2")
    ]
    checked = 0
    for q in phrasings:
        r = h(q)
        assert r is not None and r["operation"] == "assemble"
        assert r["calculation_status"] == "partial"
        assert "можешь не перепроверять" not in r["answer"], q
        # число в строке итога — то, что посчитала трасса, а не то, что подобрал тон
        summary = r["scenario"]["trace"]["sections"][0]["positions"][0]["summary"]
        shown = next(line for line in r["answer"].splitlines() if "позиции:" in line)
        assert shown.startswith("Известная стоимость позиции: "), q
        assert _fmt_num(summary["known_amount"]) in shown, q
        assert summary["full_amount"] is None, q
        checked += 1
    assert checked == len(phrasings) == 28


def test_unclosed_position_without_a_flag_names_its_own_reason(monkeypatch):
    """`partial` без ⚠-флага не имеет права выглядеть готовой суммой.

    Обычная дыра (`price_missing`) приходит и флагом, и основанием; основание шире
    (`nr_sp_unresolved`, `fsem_unresolved`, `coefficient_*`).  Канал печатает основания
    трассы, если своей строки-флага нет, — и не переводит их в свою формулировку.
    """
    from proxy.services import gesn_service
    from proxy.smeta_core import calculator

    class _Status:
        value = "partial"

    class _Scenario:
        calculation_status = _Status()
        evidence_status = _Status()
        trace = {"sections": [{"positions": [{"summary": {
            "ozp": 1.0, "em": 2.0, "mat": 3.0, "direct": 6.0, "fot": 1.0,
            "nr": None, "sp": None, "total": 6.0, "known_amount": 6.0,
            "full_amount": None, "amount_status": "partial",
            "completeness_reasons": ["nr_sp_unresolved"], "flags": [],
        }}]}]}

        def as_dict(self):
            return {}

    monkeypatch.setattr(gesn_service, "get_norm",
                        lambda code: {"name": "Позиция без НР/СП", "unit": "1 м2"})
    monkeypatch.setattr(calculator, "calculate_scenario", lambda *a, **k: _Scenario())

    answer = h("собери ГЭСН12-01-034-02 объём 1 м2")["answer"]

    assert "Известная стоимость позиции: 6.00 руб." in answer
    assert "⚠ Позиция закрыта не полностью: nr_sp_unresolved" in answer
    assert "Всего по позиции" not in answer


def test_answer_of_a_calculation_that_never_ran_has_no_assembled_frame(gold_pricebook):
    """Голому номеру без типа базы тон не выдаёт рамку «Собрала. Считал код…»."""
    r = h("собери 12-01-034-02 объём 5 м2")

    assert r["calculation_status"] == "not_calculated"
    assert r["answer"].startswith("Для расчёта нужен полный шифр")


def test_non_smeta_falls_through():
    assert h("привет как дела") is None
    assert h("посчитай смету") is None
    assert h("") is None


def test_object_and_mass_estimates_do_not_use_quick_smeta_channel():
    assert h("посчитай смету на дом 150 м2") is None
    assert h("дай смету на бетонную дачу 300 метров") is None
    assert h("стальные ярусы масса 664 711 кг, учти высотные работы") is None
