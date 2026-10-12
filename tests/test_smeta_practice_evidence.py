"""Практика раздела как свидетельство, а не как вес.

ПОЧЕМУ ТАК. Ревью 10.09 показало две вещи. Во-первых, рабочий маршрут сметного чата
идёт через `retrieve_smeta_norm_cards` → `browse_norms`, минуя `search_norm`, поэтому
вес в `search_norm` на пользовательскую смету не влиял вовсе. Во-вторых, вес двигал
порядок сильнее, чем допустимо: норма с 40-го места при 13 применениях обгоняла первую
по тексту, и редкая верная норма могла вовсе не дойти до модели.

Поэтому частота применения больше не участвует в оценке. Она прикладывается к карточке
как отдельное свидетельство с происхождением — сколько смет, какого раздела, из какого
корпуса, — а решение остаётся за моделью и проверяющим. Частота применения не
доказывает технологическую применимость.
"""

from __future__ import annotations

import json

import pytest

from proxy.smeta_core.estimate_usage import usage_evidence


@pytest.fixture()
def corpus(tmp_path):
    payload = {
        "schema": "les.smeta.estimate-usage-corpus.v1",
        "source": "E:/Сметы",
        "revision": "corpus-test-1",
        "sections": {
            "communications": {
                "files": 125,
                "applications": 2730,
                "norms": [
                    {"norm_code": "ГЭСНм11-04-028-01", "count": 90, "unit": "шт",
                     "title": "Разъём штепсельный", "in_base": True},
                    {"norm_code": "ГЭСНм10-04-087-05", "count": 1, "unit": "компл",
                     "title": "Комплект коммутационного оборудования", "in_base": True},
                ],
            },
        },
    }
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_evidence_names_its_origin(corpus):
    """Модель должна видеть, откуда цифра, иначе это не свидетельство, а мнение."""
    evidence = usage_evidence("ГЭСНм11-04-028-01", "communications", path=corpus)
    assert evidence["applications"] == 90
    assert evidence["section"] == "communications"
    assert evidence["section_files"] == 125
    assert evidence["source"] == "E:/Сметы"
    assert evidence["revision"] == "corpus-test-1"
    assert "90" in evidence["note"]


def test_evidence_is_absent_when_the_archive_is_silent(corpus):
    """Отсутствие нормы в архиве — не довод против неё, поэтому и записи нет."""
    assert usage_evidence("ГЭСН15-03-002-01", "communications", path=corpus) == {}
    assert usage_evidence("ГЭСНм11-04-028-01", "", path=corpus) == {}


def test_rare_application_is_reported_as_rare(corpus):
    """Одно применение и девяносто — разные основания, и это должно быть видно."""
    rare = usage_evidence("ГЭСНм10-04-087-05", "communications", path=corpus)
    frequent = usage_evidence("ГЭСНм11-04-028-01", "communications", path=corpus)
    assert rare["applications"] == 1
    assert frequent["applications"] == 90
    assert rare["note"] != frequent["note"]


def test_search_norm_keeps_the_text_order(monkeypatch):
    """Порядок кандидатов задаёт текстовое сходство; практика его не двигает.

    Проверка на случае из ревью: норма с последнего места пула, применённая в архиве
    много раз, не должна вытеснять первую по тексту.
    """
    from proxy.services import estimate_harness_service as harness
    import proxy.smeta_core.norm_browser as browser

    cards = [
        {"norm_code": "ГЭСНм10-03-029-01", "title": "Патч-панель", "measure_unit": "шт"},
        {"norm_code": "ГЭСНм11-04-028-01", "title": "Разъём штепсельный", "measure_unit": "шт"},
    ]
    monkeypatch.setattr(browser, "browse_norms", lambda *a, **k: {"cards": cards})
    monkeypatch.setattr(
        "proxy.smeta_core.estimate_usage.usage_evidence",
        lambda code, section, **kw: (
            {"applications": 90, "section": section, "note": "применяется часто"}
            if code == "ГЭСНм11-04-028-01" else {}
        ),
    )

    result = harness.search_norm("монтаж патч-панели", top_k=2, discipline="communications")
    assert [c["norm_code"] for c in result["candidates"]] == [
        "ГЭСНм10-03-029-01", "ГЭСНм11-04-028-01",
    ]
    # Свидетельство приложено к той норме, о которой оно говорит.
    assert result["candidates"][0].get("usage_evidence") in (None, {})
    assert result["candidates"][1]["usage_evidence"]["applications"] == 90


def test_smeta_cards_carry_the_evidence_in_the_live_route(monkeypatch):
    """Свидетельство должно доходить до модели тем маршрутом, которым она ходит.

    Сметный чат зовёт `retrieve_smeta_norm_cards`, а не `search_norm`; без этого
    подключения практика не влияет на пользовательскую смету никак.
    """
    from proxy.services import model_research_tool_service as service

    monkeypatch.setattr(
        "proxy.smeta_core.norm_browser.browse_norms",
        lambda query, **kw: {
            "cards": [
                {"norm_code": "ГЭСНм11-04-028-01", "title": "Разъём штепсельный"},
                {"norm_code": "ГЭСН15-03-002-01", "title": "Гипсовые розетки"},
            ],
            "backend": "typed_sqlite_fts",
        },
    )
    monkeypatch.setattr(
        "proxy.smeta_core.estimate_usage.usage_evidence",
        lambda code, section, **kw: (
            {"applications": 90, "section": section, "note": "применяется часто"}
            if code == "ГЭСНм11-04-028-01" else {}
        ),
    )

    payload = service.retrieve_smeta_norm_cards(
        "включение разъёмов штепсельных", discipline="communications",
    )
    cards = payload["cards"]
    assert [c["norm_code"] for c in cards] == ["ГЭСНм11-04-028-01", "ГЭСН15-03-002-01"]
    assert cards[0]["usage_evidence"]["applications"] == 90
    assert "usage_evidence" not in cards[1] or not cards[1]["usage_evidence"]


def test_text_guess_still_works_when_the_section_is_unknown(monkeypatch):
    """Если раздел не передан, остаётся догадка по тексту — но только уверенная."""
    from proxy.services import model_research_tool_service as service

    monkeypatch.setattr(
        "proxy.smeta_core.norm_browser.browse_norms",
        lambda query, **kw: {"cards": [{"norm_code": "ГЭСНм10-01-055-02", "title": "Кабель"}]},
    )
    seen: dict[str, str] = {}

    def evidence(code, section, **kw):
        seen["section"] = section
        return {"applications": 5, "section": section, "note": "редко"}

    monkeypatch.setattr("proxy.smeta_core.estimate_usage.usage_evidence", evidence)
    service.retrieve_smeta_norm_cards("прокладка кабеля U/UTP в лотке")
    assert seen["section"] == "communications"


def test_unknown_discipline_adds_nothing(monkeypatch):
    """Без распознанного раздела практики нет: приписать чужой раздел хуже, чем молчать."""
    from proxy.services import model_research_tool_service as service

    monkeypatch.setattr(
        "proxy.smeta_core.norm_browser.browse_norms",
        lambda query, **kw: {"cards": [{"norm_code": "ГЭСНм11-04-028-01", "title": "Разъём"}]},
    )
    payload = service.retrieve_smeta_norm_cards("монтаж шпильки М8")
    assert not payload["cards"][0].get("usage_evidence")


def test_section_comes_from_the_request_context(monkeypatch):
    """Раздел берётся из запроса и вложения, а не угадывается по строке работы.

    Модель спрашивает нормы построчно: «Монтаж шпильки М8», «Монтаж кабельного
    организатора 1U». Дисциплины в таких строках нет, хотя раздел ведомости назван
    прямо — «6.21. Монтаж системы структурированной кабельной сети».
    """
    from proxy.services.chat_evidence_application_service import smeta_discipline_for_request

    assert smeta_discipline_for_request(
        question="Составь смету на основании ВОР",
        attachment_context='Раздел 6.21. "МОНТАЖ СИСТЕМЫ СТРУКТУРИРОВАННОЙ КАБЕЛЬНОЙ СЕТИ"',
    ) == "communications"

    assert smeta_discipline_for_request(
        question="Смета на систему пожарной сигнализации",
        attachment_context="",
    ) == "fire_safety"

    # Ничего похожего — молчим, приписать чужой раздел хуже, чем не подсказать.
    assert smeta_discipline_for_request(question="Посчитай смету", attachment_context="") == ""


def test_evidence_reaches_the_text_the_model_reads(monkeypatch):
    """Свидетельство должно попасть в текст карточки, а не только в её поля.

    10.09: практика лежала в карточке отдельным полем, а текст для модели собирался из
    фиксированного набора — Шифр, Наименование, Измеритель, Состав работы. В ответах
    обоих прогонов «в архиве применяется» встречалось ноль раз: подсказка не доходила.
    """
    from proxy.services.model_research_tool_service import smeta_card_text

    text = smeta_card_text({
        "norm_code": "ГЭСНм11-04-028-01",
        "title": "Включение в аппаратуру разъемов штепсельных",
        "measure_unit": "1 разъем",
        "usage_evidence": {
            "applications": 153,
            "section": "communications",
            "note": "в архиве применяется регулярно: 153 раз из 125 смет раздела",
        },
    })
    assert "ГЭСНм11-04-028-01" in text
    assert "в архиве применяется регулярно: 153 раз" in text


def test_card_text_without_evidence_is_unchanged(monkeypatch):
    """Без свидетельства карточка выглядит как прежде — лишней строки не появляется."""
    from proxy.services import model_research_tool_service as service
    from proxy.services.model_research_tool_service import smeta_card_text

    monkeypatch.setattr(service, "norm_table_variants", lambda code: ())
    text = smeta_card_text({
        "norm_code": "ГЭСН15-03-002-01",
        "title": "Установка гипсовых штучных розеток",
        "measure_unit": "100 шт",
    })
    assert text.splitlines() == [
        "Шифр: ГЭСН15-03-002-01",
        "Измеритель: 100 шт",
        "Наименование: Установка гипсовых штучных розеток",
    ]


def test_tool_answer_states_that_codes_come_only_from_the_cards(monkeypatch):
    """Ответ инструмента обязан назвать правило выбора кода.

    10.09 модель проставила на все строки ТЕРп-08-02-12-1 — шифра такого формата в базе
    нет вовсе: там 49 747 норм и все ГЭСН. Проверка привязки это ловит («норма ГЭСН не
    найдена»), но целый проход уходит впустую, поэтому правило говорится сразу.
    """
    import asyncio

    from proxy.services.model_research_tool_service import ModelResearchToolService

    def retrieve(query, *, limit=6, **kwargs):
        return {
            "cards": [{"norm_code": "ГЭСНм10-01-055-02", "title": "Прокладка кабеля"}],
            "retrieval_trace": {"rag": {"status": "ok", "collection": "les_smeta_norm_cards"}},
        }

    async def _retrieve(*args, **kwargs):
        return []

    service = ModelResearchToolService(
        retrieve=_retrieve,
        frozen_dataset_ids=(),
        retrieval_kwargs={},
        fallback=lambda *a, **k: [],
        smeta_norm_retrieve=retrieve,
        model_evidence_k=6,
    )
    result = asyncio.run(service.execute({"tool": "search_sources", "args": {"q": "кабель"}}))
    rules = result.payload.get("rules") or []
    joined = " ".join(str(rule) for rule in rules)
    assert "ГЭСН" in joined
    assert "ТЕР" in joined


def test_card_lists_real_variants_not_a_range(monkeypatch):
    """Перечисляем существующие номера, а не диапазон от единицы до их числа.

    Ревью Codex 10.09: у 229 таблиц из 8 090 номера идут с пропусками. У
    ГЭСН04-01-077 всего два варианта — -09 и -10, — и справка «с -01 по -02» назвала
    бы модели два несуществующих кода. Механизм, поставленный против выдумок, сам
    начал их порождать.
    """
    from proxy.services import model_research_tool_service as service

    monkeypatch.setattr(service, "norm_table_variants", lambda code: ("09", "10"))
    text = service.smeta_card_text({
        "norm_code": "ГЭСН04-01-077-09",
        "title": "Разработка грунта",
        "measure_unit": "1000 м3",
    })
    assert "-09" in text and "-10" in text
    assert "-01" not in text.replace("ГЭСН04-01-077", "")


def test_long_variant_list_is_shortened_without_inventing(monkeypatch):
    """Длинный перечень сокращаем явным «и другие», а не диапазоном."""
    from proxy.services import model_research_tool_service as service

    monkeypatch.setattr(
        service, "norm_table_variants",
        lambda code: tuple(f"{n:02d}" for n in range(1, 31)),
    )
    text = service.smeta_card_text({
        "norm_code": "ГЭСНм10-01-001-04",
        "title": "Прокладка кабеля",
        "measure_unit": "100 м",
    })
    assert "30" in text


def test_card_tells_how_many_variants_the_table_has(monkeypatch):
    """Модель должна видеть границу таблицы, иначе продолжает ряд номеров сама.

    Прогон 10.09, 12:31: модель нашла верную таблицу ГЭСНм10-01-001 — прокладка кабеля
    в сетях связи — и выписала варианты с -01 по -21. В базе их пятнадцать, поэтому
    47 строк из 70 получили статус norm_not_found. Формат кода при этом верный: она не
    выдумывала шифр, а достраивала ряд, не зная, где он кончается.
    """
    from proxy.services import model_research_tool_service as service

    monkeypatch.setattr(service, "norm_table_variants", lambda code: tuple(f"{n:02d}" for n in range(1, 16)))
    text = service.smeta_card_text({
        "norm_code": "ГЭСНм10-01-001-04",
        "title": "Прокладка кабеля",
        "measure_unit": "100 м",
    })
    assert "ГЭСНм10-01-001" in text
    assert "всего 15" in text
    # Справка, а не запрет: «Других номеров нет» прочиталось как «аналог не ищи», и
    # модель отказалась от нормы на 55 строках из 70.
    assert "других номеров" not in text.casefold()


def test_card_stays_silent_when_the_table_size_is_unknown(monkeypatch):
    """Выдуманное число хуже отсутствующего: без данных строки в карточке нет."""
    from proxy.services import model_research_tool_service as service

    monkeypatch.setattr(service, "norm_table_variants", lambda code: ())
    text = service.smeta_card_text({
        "norm_code": "ГЭСНм10-01-001-04",
        "title": "Прокладка кабеля",
        "measure_unit": "100 м",
    })
    assert "варианты таблицы" not in text.casefold()


def test_variants_follow_the_active_base(tmp_path, monkeypatch):
    """Перечень вариантов обязан меняться вслед за активной базой.

    Ревью Codex 10.09: ключ кеша содержал только код нормы, поэтому после переключения
    базы карточка показывала прежний список. На двух временных базах смена (-09, -10) →
    (-09, -11) становилась видна лишь после ручной очистки кеша.
    """
    import sqlite3

    from proxy.services import model_research_tool_service as service

    def make(path, codes):
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE norms (display_code TEXT)")
            conn.executemany("INSERT INTO norms VALUES (?)", [(code,) for code in codes])

    first = tmp_path / "one.sqlite"
    second = tmp_path / "two.sqlite"
    make(first, ["ГЭСН04-01-077-09", "ГЭСН04-01-077-10"])
    make(second, ["ГЭСН04-01-077-09", "ГЭСН04-01-077-11"])

    import proxy.smeta_core.norm_browser as browser

    monkeypatch.setattr(browser, "_base_path", lambda: first)
    assert service.norm_table_variants("ГЭСН04-01-077-09") == ("09", "10")

    monkeypatch.setattr(browser, "_base_path", lambda: second)
    assert service.norm_table_variants("ГЭСН04-01-077-09") == ("09", "11")


def test_card_names_the_origin_of_the_practice(monkeypatch):
    """Модель должна видеть, откуда взята цифра, иначе это мнение, а не свидетельство.

    Ревью Codex 10.09: `usage_evidence` несёт section, source и revision, но в текст
    карточки уходил только рассказ о частоте. Происхождение терялось ровно там, где
    оно нужно — перед глазами модели.
    """
    from proxy.services import model_research_tool_service as service

    monkeypatch.setattr(service, "norm_table_variants", lambda code: ())
    text = service.smeta_card_text({
        "norm_code": "ГЭСНм11-04-028-01",
        "title": "Включение разъёмов",
        "measure_unit": "1 разъем",
        "usage_evidence": {
            "applications": 153,
            "section": "communications",
            "section_files": 125,
            "source": "E:/Сметы",
            "revision": "20260910T070324Z",
            "note": "в архиве применяется регулярно: 153 раз из 125 смет раздела",
        },
    })
    assert "communications" in text
    assert "E:/Сметы" in text
    assert "20260910T070324Z" in text
    assert "153 раз" in text


def test_practice_line_survives_without_origin_fields(monkeypatch):
    """Неполное свидетельство не должно ломать карточку — печатаем что есть."""
    from proxy.services import model_research_tool_service as service

    monkeypatch.setattr(service, "norm_table_variants", lambda code: ())
    text = service.smeta_card_text({
        "norm_code": "ГЭСНм11-04-028-01",
        "title": "Включение разъёмов",
        "measure_unit": "1 разъем",
        "usage_evidence": {"applications": 5, "note": "в архиве применяется редко: 5 раз"},
    })
    assert "5 раз" in text


def test_card_puts_decision_facts_before_the_long_work_steps(monkeypatch):
    """Практика и варианты таблицы идут выше состава работ.

    Бюджет режет тело карточки с хвоста, а состав работы бывает длиннее всего
    остального вместе взятого (замер 10.09: медиана карточки 437 символов, максимум
    642 при резерве 240). Если практика и перечень вариантов стоят последними, до
    модели доходит именно то, что ей нужно меньше всего.
    """
    from proxy.services import model_research_tool_service as service

    monkeypatch.setattr(service, "norm_table_variants", lambda code: ("01", "02", "03"))
    text = service.smeta_card_text({
        "norm_code": "ГЭСНм10-01-055-02",
        "title": "Прокладка кабеля",
        "measure_unit": "100 м",
        "work_steps": ["Разметка трассы", "Прокладка", "Крепление", "Маркировка"],
        "usage_evidence": {"applications": 153, "note": "применяется регулярно: 153 раз"},
    })
    lines = text.splitlines()
    practice = next(i for i, line in enumerate(lines) if line.startswith("Практика"))
    variants = next(i for i, line in enumerate(lines) if line.startswith("Варианты"))
    steps = next(i for i, line in enumerate(lines) if line.startswith("Состав"))
    assert practice < steps, "практика важнее состава работ и не должна обрезаться первой"
    assert variants < steps, "перечень вариантов не должен теряться при обрезке"


def test_work_steps_are_not_trimmed_while_there_is_room(monkeypatch):
    """Состав работы не режется в карточке: под бюджет его режет упаковщик.

    Ревью Codex 10.09: безусловный потолок 160 символов отрезал содержание, нужное
    для выбора между похожими нормами, даже когда места было вдоволь. Замер по базе:
    33 957 норм с составом, медиана 157, p90 = 404 — потолок задевал 47,5 % из них.
    При боевом же бюджете тело карточки всё равно ограничено 252 символами, и потолок
    160 против 640 давал одинаковый пакет: 23 запроса из 51, состав в 1 % карточек.
    """
    from proxy.services import model_research_tool_service as service

    monkeypatch.setattr(service, "norm_table_variants", lambda code: ())
    text = service.smeta_card_text({
        "norm_code": "ГЭСН29-02-069-01",
        "title": "Устройство деформационных швов",
        "measure_unit": "100 м",
        "work_steps": [f"Операция номер {n} с довольно длинным описанием" for n in range(1, 9)],
    })
    steps_line = next(line for line in text.splitlines() if line.startswith("Состав"))
    assert "…" not in steps_line, "состав из восьми операций короче p99 и обязан быть целым"
    assert "Операция номер 8" in steps_line


def test_giant_work_steps_still_have_a_ceiling(monkeypatch):
    """Единичные гиганты всё же ограничены: максимум состава в базе — 2 219 символов."""
    from proxy.services import model_research_tool_service as service

    monkeypatch.setattr(service, "norm_table_variants", lambda code: ())
    text = service.smeta_card_text({
        "norm_code": "ГЭСН29-02-069-01",
        "title": "Устройство деформационных швов",
        "measure_unit": "100 м",
        "work_steps": [f"Операция номер {n} с довольно длинным описанием" for n in range(1, 80)],
    })
    steps_line = next(line for line in text.splitlines() if line.startswith("Состав"))
    assert "…" in steps_line
    assert len(steps_line) <= service.WORK_STEPS_MAX_CHARS + 40
