"""Практика раздела как источник кандидатов, а не пометка на чужих карточках.

ЗАЧЕМ. Корпус применений собран из 2 279 готовых смет и знает по разделу связи 252
нормы. До сих пор он умел только приписать «применялась N раз» той карточке, которую
поиск нашёл сам: в живом прогоне 11.09 практика была у 2 карточек из 22, а нормы,
которыми связь закрывают в готовых сметах, модель не видела вовсе (ревью Codex 11.09).

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ. Не весом и не запретом: порядок поисковой выдачи не меняется,
редкая норма вне архива остаётся доступной, решение принимает модель.
"""

from __future__ import annotations

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.practice_candidates_service import (
    practice_candidate_codes,
    practice_query_label,
)


def _corpus(monkeypatch, norms):
    from proxy.smeta_core import estimate_usage

    monkeypatch.setattr(
        estimate_usage, "load_corpus",
        lambda *_a, **_k: {"sections": {"communications": {"norms": norms}}},
    )


def test_candidates_come_in_order_of_real_use(monkeypatch):
    _corpus(monkeypatch, [
        {"norm_code": "ГЭСНм11-04-008-01", "count": 186, "title": "Блоки", "in_base": True},
        {"norm_code": "ГЭСНм10-01-052-07", "count": 79, "title": "Кроссировка", "in_base": True},
    ])
    codes = [item["norm_code"] for item in practice_candidate_codes("communications")]
    assert codes == ["ГЭСНм11-04-008-01", "ГЭСНм10-01-052-07"]


def test_a_norm_already_shown_is_not_offered_twice(monkeypatch):
    _corpus(monkeypatch, [
        {"norm_code": "ГЭСНм11-04-008-01", "count": 186, "in_base": True},
        {"norm_code": "ГЭСНм10-01-052-07", "count": 79, "in_base": True},
    ])
    codes = [
        item["norm_code"]
        for item in practice_candidate_codes("communications", exclude=("гэснм11-04-008-01",))
    ]
    assert codes == ["ГЭСНм10-01-052-07"]


def test_a_norm_outside_the_active_base_is_not_offered(monkeypatch):
    """Сослаться на карточку, которой нет, модель не сможет — и расчёт её отвергнет."""
    _corpus(monkeypatch, [
        {"norm_code": "ТЕРм10-01-055-02", "count": 300, "in_base": False},
        {"norm_code": "ГЭСНм10-01-052-07", "count": 79, "in_base": True},
    ])
    codes = [item["norm_code"] for item in practice_candidate_codes("communications")]
    assert codes == ["ГЭСНм10-01-052-07"]


def test_the_label_does_not_order_the_model_to_choose():
    """Статистика не заменяет решение сметчика — заголовок объясняет происхождение."""
    label = practice_query_label("communications", 8)
    assert "чаще всего применяли" in label
    assert "не обязательный выбор" in label
    assert "ищи дальше" in label


def test_an_unknown_section_offers_nothing(monkeypatch):
    _corpus(monkeypatch, [])
    assert practice_candidate_codes("communications") == []
    assert service.smeta_practice_group(
        attachment_context="Добрый день, договор", question="привет", already_shown=[],
    ) is None


def test_the_funnel_separates_four_different_losses():
    """Найдена → показана → выбрана → рассчитана: четыре разные задачи.

    Одно число «решено 9 из 70» не говорит, что чинить: поиск, бюджет окна, подбор
    или расчёт (ревью Codex 11.09).
    """
    class _Chunk:
        def __init__(self, code, practice=False):
            self.meta = {"norm_code": code, "practice_candidate": practice}

    funnel = service.smeta_selection_funnel(
        query_hits=[
            ("практика раздела", (_Chunk("A", True), _Chunk("B", True))),
            ("поиск", (_Chunk("C"), _Chunk("D"), _Chunk("E"))),
        ],
        shown_chunks=[_Chunk("A", True), _Chunk("C")],
        rows=[
            {"source_row": "1", "norm_code": "A"},
            {"source_row": "2", "norm_code": "C"},
            {"source_row": "3", "norm_code": ""},
        ],
        rejected={"2": "unit_conflict"},
        bound_rows=1,
    )
    assert funnel["rows_calculated"] == 1
    assert funnel["norms_found"] == 5
    assert funnel["norms_shown"] == 2
    assert funnel["norms_lost_to_budget"] == 3, "три нормы нашлись, но не влезли в окно"
    assert funnel["practice_offered"] == 2
    assert funnel["practice_selected"] == 1, "одну норму модель взяла из практики"
    assert funnel["norms_selected"] == 2
    assert funnel["rows_with_norm"] == 2
    assert funnel["rows_rejected_by_calc"] == 1
    assert funnel["reject_reasons"] == ["unit_conflict"]


def test_practice_group_goes_first_so_the_budget_cuts_search_not_it():
    """Группа практики идёт первой: бюджет режет хвост, а не единственный её источник."""
    import inspect

    source = inspect.getsource(service._execute_chat_evidence_application)
    assert "model_rag_query_hits.insert(0, practice_group)" in source


def test_the_funnel_counts_rows_and_norms_apart():
    """Одна норма закрывает несколько строк — вычитать одно из другого нельзя.

    Ревью Codex 11.09: «выбрано» считалось уникальными шифрами, «отвергнуто» —
    строками, и разность давала `calculated = -1`. Успех берётся из фактического
    результата расчётчика, а при его отсутствии остаётся пустым: нет данных — не успех.
    """
    class _Chunk:
        def __init__(self, code):
            self.meta = {"norm_code": code, "practice_candidate": False}

    funnel = service.smeta_selection_funnel(
        query_hits=[("поиск", (_Chunk("A"),))],
        shown_chunks=[_Chunk("A")],
        rows=[
            {"source_row": "1", "norm_code": "A"},
            {"source_row": "2", "norm_code": "A"},
            {"source_row": "3", "norm_code": ""},
        ],
        rejected={"1": "unit_conflict", "2": "unit_conflict"},
    )
    assert funnel["rows"] == 3
    assert funnel["rows_with_norm"] == 2, "две строки получили норму"
    assert funnel["norms_selected"] == 1, "норма при этом одна"
    assert funnel["rows_rejected_by_calc"] == 2
    assert funnel["rows_calculated"] is None, "расчётчик не отчитался — успеха нет"

    with_result = service.smeta_selection_funnel(
        query_hits=[("поиск", (_Chunk("A"),))], shown_chunks=[_Chunk("A")],
        rows=[{"source_row": "1", "norm_code": "A"}], rejected={}, bound_rows=1,
    )
    assert with_result["rows_calculated"] == 1


def test_funnel_does_not_attribute_whole_workbook_to_current_portion():
    funnel = service.smeta_selection_funnel(
        query_hits=[], shown_chunks=[],
        rows=[{"source_row": 997, "norm_code": "A"},
              {"source_row": 1015, "norm_code": "B"}],
        rejected={"997": "unit_conflict", "984": "resource_parent_missing",
                  "1015": "coefficient_needs_basis"},
        bound_rows=42, includes_prior_rows=True,
    )
    assert funnel["rows"] == 2
    assert funnel["rows_calculated"] is None
    assert funnel["workbook_rows_calculated"] == 42
    assert funnel["rows_rejected_by_calc"] == 1
    assert funnel["reject_reasons"] == ["unit_conflict"]
    assert funnel["rows_with_calc_diagnostics"] == 2


def test_funnel_uses_row_results_for_current_materials_and_partial_results():
    args = dict(query_hits=[], shown_chunks=[],
                rows=[{"source_row": "2", "norm_code": ""},
                      {"source_row": "3", "norm_code": ""}],
                bound_rows=42, includes_prior_rows=True)
    result = service.smeta_selection_funnel(
        **args, row_statuses={"1": "bound", "2": "material_bound", "3": "material_price_missing"})
    assert result["rows_calculated"] == 1
    assert result["rows_rejected_by_calc"] == 1
    assert result["workbook_rows_calculated"] == 42
    assert service.smeta_selection_funnel(**args, row_statuses={"2": "material_bound"})["rows_calculated"] is None


def test_practice_never_evicts_a_search_query():
    """Практика не стоит ни одного поискового запроса — ни на каком бюджете.

    Ревью Codex 11.09: сперва её группа выбрасывала второй запрос целиком; после
    ужатия до двух карточек она выталкивала его снова при более тесном бюджете.
    Запрос, сформулированный под конкретную строку ведомости, ценнее справки о
    разделе, поэтому при нехватке места практика уходит целиком.
    """
    class _Hit:
        def __init__(self, code, practice=False):
            self.meta = {"norm_code": code, "practice_candidate": practice}
            self.content = f"Шифр: {code}. " + "Наименование работы. " * 14
            self.doc_name = "cards"
            self.score = 1.0

    search = [
        ("запрос 1", tuple(_Hit(f"S1-{i}") for i in range(3))),
        ("запрос 2", tuple(_Hit(f"S2-{i}") for i in range(3))),
    ]
    practice = ("практика раздела", tuple(_Hit(f"P-{i}", True) for i in range(8)))

    for budget in (3200, 2600, 2200, 1900, 1500, 1200, 900, 700):
        _g, alone = service.build_model_rag_evidence_groups(
            search, max_chars=budget, hits_per_query=5,
        )
        _g, together = service.build_model_rag_evidence_groups(
            [practice, *search], max_chars=budget, hits_per_query=5,
        )
        only_search = lambda chunks: [
            c for c in chunks if not c.meta["norm_code"].startswith("P")
        ]
        assert len(only_search(together)) >= len(only_search(alone)), (
            f"на бюджете {budget} практика отняла место у поиска"
        )

    _g, roomy = service.build_model_rag_evidence_groups(
        [practice, *search], max_chars=3200, hits_per_query=5,
    )
    assert any(c.meta["norm_code"].startswith("P") for c in roomy), (
        "когда места хватает, практика обязана быть в пакете"
    )
