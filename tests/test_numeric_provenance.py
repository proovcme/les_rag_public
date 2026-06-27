"""Numeric provenance гард (Codex §8, пет-размер) — метит числа без основания в контексте."""

from proxy.services.saferag_service import numeric_provenance_check as chk


def test_number_in_context_not_flagged():
    assert chk("Расход кабеля 15030.72 м.", "по ведомости кабель 15 030,72 м") == []


def test_number_absent_from_context_flagged():
    flags = chk("Итого 1 284 500 руб.", "контекст без этой суммы")
    assert any("1 284 500" in f for f in flags)


def test_year_and_short_numbers_ignored():
    assert chk("СП утверждён в 2023 году, пункт 5.4.3, всего 12 штук", "пустой контекст") == []


def test_normalization_matches_separators():
    # ответ «15 030,72», контекст «15030.72» → один и тот же → не флагуем
    assert chk("стоимость 15 030,72 ₽", "цена 15030.72") == []


def test_max_flags_cap():
    ans = "числа 11110 22220 33330 44440 55550 66660 77770"
    assert len(chk(ans, "пусто")) <= 5


def test_empty_safe():
    assert chk("", "") == []
    assert chk("просто текст без чисел", "контекст") == []
