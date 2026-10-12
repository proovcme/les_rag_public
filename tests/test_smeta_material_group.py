"""Группа кандидатов по наименованию изделия: что попадает в окно модели.

Группа раздела одинакова для всей ведомости и отвечает на конкретную строку только
случайно. Замер 11.09.2026 по 56 нерешённым строкам прогона `sks-unit-20260911-0806`:
поиск по нормам попал в профильный сборник 11 раз, подбор по наименованию изделия — 51.
"""

from __future__ import annotations

from typing import Any

import pytest

from proxy.services.chat_evidence_application_service import smeta_material_group


class _Hit:
    def __init__(self, norm_code: str) -> None:
        self.meta = {"norm_code": norm_code}


def application(norm_code: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "norm_code": norm_code,
        "norm_title": "Провод в лотках, сечением: до 6 мм2",
        "norm_unit": "100 м",
        "material": "Кабель витая пара, неэкранированная U/UTP, категория 5e",
        "material_unit": "м",
        "applications": 34,
        "demolition": False,
        "equipment": False,
        "score": 0.71,
        "confidence": "совпадение наименований",
    }
    payload.update(extra)
    return payload


@pytest.fixture()
def answers(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    """Подменяет подбор и базу норм: тест проверяет сборку группы, а не сам поиск."""
    table: dict[str, list[dict[str, Any]]] = {}

    def fake(title: str, *, limit: int = 5, **_: Any) -> list[dict[str, Any]]:
        return list(table.get(" ".join(str(title).split()), ()))[:limit]

    def base(code: str, *, limit: int = 1, **_: Any) -> dict[str, Any]:
        if code in _ABSENT_FROM_BASE:
            return {"cards": []}
        return {"cards": [{
            "norm_code": code,
            "norm_id": f"id-{code}",
            "title": "Провод в лотках, сечением: до 6 мм2",
            "measure_unit": "100 м",
            "work_steps": ["Разметка трассы", "Прокладка провода"],
        }]}

    monkeypatch.setattr(
        "proxy.smeta_core.material_practice.similar_applications", fake
    )
    monkeypatch.setattr("proxy.smeta_core.norm_browser.browse_norms", base)
    return table


# Шифры, которых «нет в активной базе»: заполняется отдельными тестами.
_ABSENT_FROM_BASE: set[str] = set()


def test_no_titles_means_no_group(answers: dict[str, Any]) -> None:
    """Пустая порция не должна давать пустую группу — её вставили бы в окно зря."""
    assert smeta_material_group(titles=[], already_shown=()) is None


def test_group_answers_each_row_separately(answers: dict[str, Any]) -> None:
    """Ради этого группа и заводится: раздел один на ведомость, строки разные."""
    answers["Кабель витая пара U/UTP"] = [application("ГЭСНм08-02-398-01")]
    answers["Шпилька М8х2000"] = [
        application(
            "ГЭСНм08-02-395-01",
            material="Шпилька М8х2000 CM200802",
            norm_title="Лоток металлический штампованный",
            norm_unit="1 т",
            applications=13,
        )
    ]
    group = smeta_material_group(
        titles=["Кабель витая пара U/UTP", "Шпилька М8х2000"], already_shown=()
    )
    assert group is not None
    label, cards = group
    assert "изделия" in label
    assert [card.meta["norm_code"] for card in cards] == [
        "ГЭСНм08-02-398-01",
        "ГЭСНм08-02-395-01",
    ]


def test_search_code_does_not_hide_distinct_archive_provenance(answers: dict[str, Any]) -> None:
    """A search code alone does not carry the archived product/source example."""
    answers["Кабель витая пара U/UTP"] = [application("ГЭСНм08-02-398-01")]
    shown = [("запрос", (_Hit("ГЭСНм08-02-398-01"),))]
    group = smeta_material_group(titles=["Кабель витая пара U/UTP"], already_shown=shown)
    assert group is not None
    assert 'Кабель витая пара' in group[1][0].content


def test_available_alternatives_do_not_hide_later_rows(answers):
    answers['First'] = [application('ГЭСНм08-02-398-01'), application('ГЭСНм08-02-398-02')]
    answers['Second'] = [application('ГЭСНм08-02-399-01'), application('ГЭСНм08-02-399-02')]
    group = smeta_material_group(titles=['First', 'Second'], already_shown=())
    assert [c.meta['norm_code'] for c in group[1]] == [
        'ГЭСНм08-02-398-01', 'ГЭСНм08-02-399-01', 'ГЭСНм08-02-398-02', 'ГЭСНм08-02-399-02']


def test_same_norm_is_offered_once_across_rows(answers: dict[str, Any]) -> None:
    """Соседние строки ведомости считают одной нормой — показывать её дважды незачем."""
    answers["Кабель витая пара 5e"] = [application("ГЭСНм08-02-398-01")]
    answers["Кабель витая пара 6a"] = [application("ГЭСНм08-02-398-01")]
    group = smeta_material_group(
        titles=["Кабель витая пара 5e", "Кабель витая пара 6a"], already_shown=()
    )
    assert group is not None
    assert len(group[1]) == 1


def test_card_carries_the_product_it_was_matched_by(answers: dict[str, Any]) -> None:
    """Без наименования изделия дословное совпадение не отличить от общего слова."""
    answers["Кабель витая пара U/UTP"] = [application("ГЭСНм08-02-398-01")]
    group = smeta_material_group(titles=["Кабель витая пара U/UTP"], already_shown=())
    assert group is not None
    card = group[1][0]
    assert "Кабель витая пара" in card.meta["application_note"]
    assert "34" in card.meta["application_note"]


def test_the_note_reaches_the_text_the_model_reads(answers: dict[str, Any]) -> None:
    """Пояснение лежало в `source_ref`, а текст карточки это поле не выводит.

    Ровно так 10.09 терялась практика раздела; здесь та же ошибка повторилась 11.09.
    """
    answers["Кабель витая пара U/UTP"] = [application("ГЭСНм08-02-398-01")]
    group = smeta_material_group(titles=["Кабель витая пара U/UTP"], already_shown=())
    assert group is not None
    assert "Кабель витая пара" in group[1][0].content
    assert "34" in group[1][0].content


def test_measure_unit_comes_from_the_base_not_from_the_archive(
    answers: dict[str, Any]
) -> None:
    """В архивной смете стоит измеритель того расчёта; считать надо по базовому."""
    answers["Кабель витая пара U/UTP"] = [
        application("ГЭСНм08-02-398-01", norm_unit="100 м кабеля по факту")
    ]
    group = smeta_material_group(titles=["Кабель витая пара U/UTP"], already_shown=())
    assert group is not None
    assert group[1][0].meta["measure_unit"] == "100 м"


def test_every_row_of_the_portion_gets_a_hint(answers: dict[str, Any]) -> None:
    """Предел в двенадцать карточек покрывал шесть строк порции из двадцати пяти."""
    titles = [f"Изделие {number}" for number in range(25)]
    for number in range(25):
        answers[f"Изделие {number}"] = [application(f"ГЭСНм08-02-{number:03d}-01")]
    group = smeta_material_group(titles=titles, already_shown=())
    assert group is not None
    assert len(group[1]) == 25


def test_norm_missing_from_the_base_does_not_cost_the_row_its_hint(
    answers: dict[str, Any]
) -> None:
    """Ненайденная норма пропускается, но строка не должна молча остаться без подсказки."""
    answers["Кабель витая пара U/UTP"] = [
        application("ГЭСНм99-99-999-99"),
        application("ГЭСНм08-02-398-01"),
    ]
    _ABSENT_FROM_BASE.add("ГЭСНм99-99-999-99")
    try:
        group = smeta_material_group(titles=["Кабель витая пара U/UTP"], already_shown=())
        assert group is not None
        assert [card.meta["norm_code"] for card in group[1]] == ["ГЭСНм08-02-398-01"]
    finally:
        _ABSENT_FROM_BASE.discard("ГЭСНм99-99-999-99")


def test_demolition_is_stated_on_the_card(answers: dict[str, Any]) -> None:
    """Без пометки «Кабель BC5E-4-LSHF» тянул бы за собой «Демонтаж кабеля» молча."""
    answers["Кабель BC5E-4-LSHF"] = [
        application("ГЭСНр67-03-001-01", norm_title="Демонтаж кабеля", demolition=True)
    ]
    group = smeta_material_group(titles=["Кабель BC5E-4-LSHF"], already_shown=())
    assert group is not None
    card = group[1][0]
    assert card.meta["demolition"] is True
    assert "демонтажная" in card.meta["application_note"]
    assert "демонтажная" in card.content


def test_row_limit_keeps_one_row_from_taking_the_window(answers: dict[str, Any]) -> None:
    """Одна строка с десятком применений вытеснила бы из окна остальные."""
    answers["Кабель витая пара U/UTP"] = [
        application(f"ГЭСНм08-02-398-0{n}") for n in range(1, 6)
    ]
    group = smeta_material_group(
        titles=["Кабель витая пара U/UTP"], already_shown=(), limit_per_row=2
    )
    assert group is not None
    assert len(group[1]) == 2


def test_total_limit_is_respected(answers: dict[str, Any]) -> None:
    """Группа идёт первой в окне: без предела она вытеснит поисковую выдачу."""
    for number in range(10):
        answers[f"Изделие {number}"] = [application(f"ГЭСНм08-02-39{number}-01")]
    group = smeta_material_group(
        titles=[f"Изделие {number}" for number in range(10)],
        already_shown=(),
        limit_per_row=1,
        limit_total=3,
    )
    assert group is not None
    assert len(group[1]) == 3


def test_failure_of_the_lookup_does_not_break_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Подсказка не обязана существовать; ответ без неё хуже, но он должен состояться."""

    def boom(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("индекс недоступен")

    monkeypatch.setattr(
        "proxy.smeta_core.material_practice.similar_applications", boom
    )
    assert smeta_material_group(titles=["Кабель"], already_shown=()) is None


def test_trace_records_what_was_offered(answers: dict[str, Any]) -> None:
    """По следу видно, была ли подсказка у строки, — иначе разбор прогона гадает."""
    answers["Кабель витая пара U/UTP"] = [application("ГЭСНм08-02-398-01")]
    trace: dict[str, Any] = {}
    smeta_material_group(
        titles=["Кабель витая пара U/UTP"], already_shown=(), trace=trace
    )
    recorded = trace["smeta_material_candidates"]
    assert recorded["offered"] == ["ГЭСНм08-02-398-01"]
    assert recorded["rows"][0]["offered"] == 1
