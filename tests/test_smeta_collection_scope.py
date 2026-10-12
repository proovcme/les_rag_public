"""Область сборников по дисциплинам: проверка на реальных ошибках подбора 09.09.

Все нормы и позиции ниже взяты из разбора артефакта `LSR_СКС_2_2026-09-09_1524.xlsx`,
собранного по спецификации СКС: там кабель U/UTP получил бестраншейную прокладку в
полосе отвода железных дорог, компьютерная розетка — гипсовую штучную, а держатель
гофротрубы — монтаж микротоннельного проходческого комплекса.
"""

from __future__ import annotations

import pytest

from proxy.smeta_core.collection_scope import (
    FOREIGN_WEIGHT,
    PRIMARY_WEIGHT,
    RELATED_WEIGHT,
    collection_affinity,
    collection_key,
    collection_reason,
    discipline_for_text,
    load_scope,
)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("ГЭСНм10-01-055-02", "ГЭСНм10"),
        ("ГЭСНм08-02-409-09", "ГЭСНм08"),
        ("ГЭСН15-03-002-01", "ГЭСН15"),
        ("ГЭСНр65-04-006-14", "ГЭСНр65"),
        ("ГЭСНп01-11-001-01", "ГЭСНп01"),
        ("ГЭСН1-01-001-01", "ГЭСН01"),
        ("не норма", ""),
        ("", ""),
    ],
)
def test_collection_key_reads_the_family_and_number(code: str, expected: str) -> None:
    assert collection_key(code) == expected


def test_scope_is_loaded_from_the_domain_config() -> None:
    scope = load_scope()
    disciplines = scope["disciplines"]
    assert "communications" in disciplines
    # Сборник 10 «Оборудование связи» — профильный для СКС.
    assert "ГЭСНм10" in disciplines["communications"]["primary"]
    # Сборник 8 «Электротехнические установки» — смежный: трассы, лотки, заземление.
    assert "ГЭСНм08" in disciplines["communications"]["related"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Прокладка кабеля U/UTP Cat.5e в лотке", "communications"),
        ("Монтаж патч-панели 19 дюймов на 24 порта", "communications"),
        ("Сварка оптических волокон, установка пигтейлов", "communications"),
        ("Монтаж воздуховода системы вентиляции", "hvac"),
        ("Прокладка внутреннего трубопровода канализации", "plumbing"),
        ("Монтаж светильника и щита электроснабжения", "electrical"),
        ("Устройство монолитной железобетонной плиты", "concrete"),
        ("Разработка грунта в траншее", "earthworks"),
        ("", ""),
        ("Нечто без признаков дисциплины", ""),
    ],
)
def test_discipline_is_recognised_by_work_text(text: str, expected: str) -> None:
    assert discipline_for_text(text) == expected


def test_several_markers_win_over_a_single_accidental_word() -> None:
    """Одно слово «кабель» не должно перетягивать работу в электрику из связи."""
    text = "Прокладка кабеля витая пара UTP для СКС в патч-панель"
    assert discipline_for_text(text) == "communications"


@pytest.mark.parametrize(
    ("code", "weight", "comment"),
    [
        ("ГЭСНм10-07-072-03", PRIMARY_WEIGHT, "оборудование связи — профильный"),
        ("ГЭСНм08-02-409-09", RELATED_WEIGHT, "электроустановки — смежный, трассы"),
        ("ГЭСН15-03-002-01", FOREIGN_WEIGHT, "отделочные работы — посторонний"),
        ("ГЭСН27-09-001-09", FOREIGN_WEIGHT, "автодороги — посторонний"),
        ("ГЭСН29-01-095-05", FOREIGN_WEIGHT, "тоннели — посторонний"),
        ("ГЭСН10-01-057-01", FOREIGN_WEIGHT, "деревянные конструкции — посторонний"),
        ("ГЭСНм01-02-045-09", FOREIGN_WEIGHT, "металлообработка — посторонний"),
    ],
)
def test_real_misassignments_get_a_negative_weight(code: str, weight: float, comment: str) -> None:
    assert collection_affinity(code, "communications") == weight, comment


def test_unknown_discipline_never_penalises_a_candidate() -> None:
    """Без распознанной дисциплины ранжирование остаётся прежним, а не случайным."""
    assert collection_affinity("ГЭСН15-03-002-01", "") == 0.0
    assert collection_affinity("ГЭСН15-03-002-01", "нет такой дисциплины") == 0.0
    assert collection_affinity("текст без кода", "communications") == 0.0


def test_reasons_are_written_for_the_check_sheet() -> None:
    assert collection_reason("ГЭСНм10-07-072-03", "communications").startswith("профильный сборник ГЭСНм10")
    assert collection_reason("ГЭСНм08-02-409-09", "communications").startswith("смежный сборник ГЭСНм08")
    reason = collection_reason("ГЭСН27-09-001-09", "communications")
    assert reason.startswith("сборник ГЭСН27 вне дисциплины")
    assert "Сети связи" in reason
    assert collection_reason("ГЭСН27-09-001-09", "") == ""


def test_foreign_collection_is_marked_for_the_reviewer(monkeypatch):
    """Норма из чужого сборника остаётся в списке, но с явным основанием сомнения.

    Живой случай: для кабеля U/UTP в кандидатах оказывались «Установка гипсовых
    штучных розеток» и «Устройство перильного ограждения» — совпадают слова, а не
    технология. Отсекать их автоматически нельзя: замер на 542 строках готовых смет
    показал, что вес сборника роняет точность первой позиции с 74,0 % до 71,0 %,
    потому что заодно топит верные нормы из смежных сборников. Поэтому сборник
    объясняет кандидата, а решение остаётся за проверяющим.
    """
    from proxy.services import estimate_harness_service as harness

    cards = [
        {"norm_code": "ГЭСН15-03-002-01", "title": "Установка гипсовых штучных розеток",
         "measure_unit": "100 шт"},
        {"norm_code": "ГЭСН27-09-001-09", "title": "Устройство перильного ограждения",
         "measure_unit": "100 м"},
        {"norm_code": "ГЭСНм10-01-055-02", "title": "Прокладка кабеля, масса 1 м: до 1 кг",
         "measure_unit": "100 м"},
    ]
    import proxy.smeta_core.norm_browser as browser
    monkeypatch.setattr(browser, "browse_norms", lambda *a, **k: {"cards": cards})

    result = harness.search_norm(
        "Прокладка кабеля U/UTP Cat.5e для СКС в патч-панель", top_k=3
    )
    assert result["discipline"] == "communications"
    scopes = {c["norm_code"]: c["collection_scope"] for c in result["candidates"]}
    assert scopes["ГЭСНм10-01-055-02"] == "primary"
    assert scopes["ГЭСН27-09-001-09"] == "foreign"

    foreign = next(c for c in result["candidates"] if c["norm_code"] == "ГЭСН27-09-001-09")
    assert "вне дисциплины" in foreign["collection_reason"]
    # Пояснение не превратилось в вес: в разборе оценки сборника нет.
    assert all("collection" not in c["score_parts"] for c in result["candidates"])


def test_practice_is_shown_next_to_the_candidate(monkeypatch):
    """Практика раздела прикладывается к кандидату и порядок не меняет."""
    from proxy.services import estimate_harness_service as harness
    import proxy.smeta_core.norm_browser as browser

    cards = [
        {"norm_code": "ГЭСН15-03-002-01", "title": "Установка гипсовых штучных розеток",
         "measure_unit": "100 шт"},
        {"norm_code": "ГЭСНм10-01-055-03", "title": "Прокладка кабеля, масса 1 м: до 2 кг",
         "measure_unit": "100 м"},
    ]
    monkeypatch.setattr(browser, "browse_norms", lambda *a, **k: {"cards": cards})
    monkeypatch.setattr(
        "proxy.smeta_core.estimate_usage.usage_evidence",
        lambda code, section, **kw: (
            {"applications": 40, "section": section, "note": "в архиве применяется регулярно: 40 раз"}
            if code == "ГЭСНм10-01-055-03" else {}
        ),
    )

    result = harness.search_norm("Прокладка кабеля U/UTP Cat.5e", top_k=2,
                                 discipline="communications")
    codes = [c["norm_code"] for c in result["candidates"]]
    assert codes == ["ГЭСН15-03-002-01", "ГЭСНм10-01-055-03"]
    assert result["candidates"][1]["usage_evidence"]["applications"] == 40


def test_search_norm_keeps_order_when_discipline_is_unknown(monkeypatch):
    """Без распознанной дисциплины порядок остаётся тем, что дал поиск."""
    from proxy.services import estimate_harness_service as harness
    import proxy.smeta_core.norm_browser as browser

    cards = [
        {"norm_code": "ГЭСН15-03-002-01", "title": "Первая", "measure_unit": "100 шт"},
        {"norm_code": "ГЭСНм10-01-055-02", "title": "Вторая", "measure_unit": "100 м"},
    ]
    monkeypatch.setattr(browser, "browse_norms", lambda *a, **k: {"cards": cards})

    result = harness.search_norm("Нечто без признаков дисциплины", top_k=2)
    assert [c["norm_code"] for c in result["candidates"]] == [
        "ГЭСН15-03-002-01",
        "ГЭСНм10-01-055-02",
    ]
    assert result["discipline"] == ""


def test_explicit_discipline_wins_over_text_guessing(monkeypatch):
    """Дисциплину задаёт раздел документа, а не отдельная строка.

    Замер 09.09: у восьми описаний из двенадцати («Монтаж шпильки М8», «Монтаж
    держателя труб 25 мм», «Монтаж шкафа напольного 42U») признаков дисциплины нет
    вовсе, хотя раздел спецификации прямо назван — «6.21. Монтаж системы
    структурированной кабельной сети».
    """
    from proxy.services import estimate_harness_service as harness
    import proxy.smeta_core.norm_browser as browser

    cards = [
        {"norm_code": "ГЭСН27-09-001-09", "title": "Перильное ограждение", "measure_unit": "100 м"},
        {"norm_code": "ГЭСНм10-06-037-01", "title": "Шкаф напольный", "measure_unit": "шт"},
    ]
    monkeypatch.setattr(browser, "browse_norms", lambda *a, **k: {"cards": cards})

    # Без подсказки текст «Монтаж шпильки М8» дисциплины не выдаёт.
    blind = harness.search_norm("Монтаж шпильки М8", top_k=2)
    assert blind["discipline"] == ""

    informed = harness.search_norm("Монтаж шпильки М8", top_k=2, discipline="communications")
    assert informed["discipline"] == "communications"
    # Названный раздел даёт нормам основание: посторонняя получает пометку «вне
    # дисциплины», профильная — «primary», и практика раздела считается по нему.
    labels = {c["norm_code"]: c["collection_scope"] for c in informed["candidates"]}
    assert labels["ГЭСНм10-06-037-01"] == "primary"
    assert labels["ГЭСН27-09-001-09"] == "foreign"


def test_unknown_explicit_discipline_is_ignored_not_trusted(monkeypatch):
    """Чужое имя дисциплины не должно ни ранжировать, ни ронять подбор."""
    from proxy.services import estimate_harness_service as harness
    import proxy.smeta_core.norm_browser as browser

    cards = [{"norm_code": "ГЭСН27-09-001-09", "title": "Перила", "measure_unit": "100 м"}]
    monkeypatch.setattr(browser, "browse_norms", lambda *a, **k: {"cards": cards})

    result = harness.search_norm("Монтаж шпильки М8", top_k=1, discipline="нет такой")
    assert result["discipline"] == ""
    assert "collection" not in result["candidates"][0]["score_parts"]
