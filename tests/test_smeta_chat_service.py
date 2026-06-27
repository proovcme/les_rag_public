"""Чат-канал «смета»: цена по коду / нужен ли КАЦ / коэф. стеснённости (0 LLM, до RAG)."""

from __future__ import annotations

from proxy.services import fgis_price_service as fps
from proxy.services.object_estimate_service import merge_parsed_requests
from proxy.services.smeta_chat_service import _answer_object_estimate, maybe_handle_smeta_query as h


def test_price_routes_even_without_book(monkeypatch):
    monkeypatch.setattr(fps, "available_pricebooks", lambda *a, **k: [])
    r = h("цена 91.05.01-017")
    assert r is not None and r["operation"] == "price"
    assert "книг" in r["answer"].lower()                 # нет книги → подсказка


def test_needs_kac_route():
    r = h("нужен ли КАЦ для 99.99.99-999")
    assert r is not None and r["operation"] == "needs_kac"


def test_stesnennost_route():
    r = h("коэффициент стеснённости для города")
    assert r is not None and r["operation"] == "stesnennost"
    assert "1.15" in r["answer"]
    assert h("какой коэффициент стеснённости")["operation"] == "stesnennost"


def test_code_extraction():
    from proxy.services.smeta_chat_service import _first_code
    assert _first_code("цена 91.05.01-017 пожалуйста") == "91.05.01-017"
    assert _first_code("сколько стоит 01.7.15.06-0111") == "01.7.15.06-0111"
    assert _first_code("нет кода тут") is None


def test_assemble_from_code_reproduces_etalon():
    r = h("собери ГЭСН12-01-034-02 объём 0.61")
    assert r is not None and r["operation"] == "assemble"
    assert "11 813.04" in r["answer"]                     # gold: Всего по позиции


def test_assemble_with_stesnennost():
    r = h("собери ГЭСН12-01-034-02 объём 0.61 стеснённость город")
    assert r["operation"] == "assemble"
    assert "13 572.45" in r["answer"] and "11 813.04" in r["answer"]  # скорр + было


def test_assemble_needs_volume():
    r = h("собери ГЭСН12-01-034-02")
    assert r["operation"] == "assemble" and "объём" in r["answer"].lower()


def test_non_smeta_falls_through():
    assert h("привет как дела") is None
    assert h("посчитай смету") is None                    # без кода/интента → дальше
    assert h("") is None


def test_object_estimate_answer_is_rough_full_object_budget():
    r = _answer_object_estimate("Офисное здание новое - 3 этажа, подвал, плоская кровля, 3000 метров")
    assert r is not None and r["operation"] == "object_estimate"
    assert "Прикидка стоимости объекта по мутному ТЗ" in r["answer"]
    assert "ОРИЕНТИР стоимости объекта" in r["answer"]
    assert "ASSUME" in r["answer"]
    assert "Подвал/подземная часть учтены" in r["answer"]
    assert "### Защита расчёта: что откуда взято" in r["answer"]
    assert "ориентир, не защищаемая ЛСР" in r["answer"]
    assert "Ценовое покрытие ресурсов" in r["answer"]
    assert "нет цены" in r["answer"]
    assert "прямые" in r["answer"] and "НР" in r["answer"] and "СП" in r["answer"]
    assert "S1=1 000.00" in r["answer"]
    assert "ASSUMED_NOT_NORMATIVE" in r["answer"]
    assert "для защиты нужен регион/квартал/индекс" in r["answer"]
    assert "воспроизводимость расчёта, не доказательство стоимости" in r["answer"]
    assert r["sources"]
    assert r["retrieval_trace"]["mode"] == "object_estimate"
    assert r["retrieval_trace"]["price_coverage"]["missing"] > 0
    assert r["defense"]["schema"] == "defense_contract_v1"
    assert r["defense"]["status"] == "not_defensible"
    assert r["evidence_summary"]["COMPUTED"] == 1
    assert r["evidence_summary"]["MISSING_PRICE"] > 0
    assert r["provenance"]["confidence"] == "rough_full_object_assumed"
    assert r["provenance"]["final_total_allowed"] is False


def test_object_estimate_uses_dialog_context_without_string_concat():
    ctx = merge_parsed_requests([
        "Хочу деревянный дом 150 м2, один этаж",
        "А давай два этажа",
    ])
    r = _answer_object_estimate("А давай два этажа", parsed_context=ctx)
    assert r is not None and r["operation"] == "object_estimate"
    assert "150.0 м², 2 эт." in r["answer"]


def test_frame_dacha_dialog_uses_context_and_nearest_local_analog():
    turns = [
        "Привет, я строю дачу! Хочу дом на сваях каркас, метров 150, один этаж, двускатная кровля.",
        "а давай два этажа!",
        "а давай крыльцо!",
        "а если фундамент?",
        "а давай плоскую кровлю",
    ]
    ctx = merge_parsed_requests(turns)
    r = _answer_object_estimate(turns[-1], parsed_context=ctx)

    assert r is not None and r["operation"] == "object_estimate"
    assert "150.0 м², 2 эт." in r["answer"]
    assert "ближайший локальный аналог" in r["answer"]
    assert "Точного шаблона под исходный материал/объект нет" in r["answer"]
    assert "Свайный фундамент" in r["answer"]
    assert "Крыльцо/терраса" in r["answer"]
    assert "Плоская кровля" in r["answer"]
    assert "Под этот объект пока нет типового шаблона" not in r["answer"]
    assert r["provenance"]["confidence"] == "rough_analog_object_assumed"
    assert r["provenance"]["analog"]["requested_material"] == "каркас"
    assert r["retrieval_trace"]["analog"]["template_id"] == "wooden_house"


def test_custom_mass_estimate_fallback_for_steel_tiers():
    q = (
        "Стальные каркасы, облицованные бронзой. Общая масса составляет 664 711,12 кг, "
        "11 ярусов. Этап 1 контрольная сборка двух смежных ярусов. Этап 2 упаковка. "
        "Этап 3 транспорт принять 0 руб. Этап 4 монтаж с колес гусеничным краном. "
        "Стоимость давальческого сырья принять 0 руб."
    )
    r = _answer_object_estimate(q)
    assert r is not None
    assert r["operation"] == "custom_mass_estimate_assumed"
    assert "стальные/бронзовые ярусы" in r["answer"]
    assert "664.71 т" in r["answer"]
    assert "ОРИЕНТИР стоимости работ" in r["answer"]
    assert "расчётное допущение" in r["answer"]
    assert "Кандидаты ГЭСН" in r["answer"]
    assert "ГЭСН:09-" in r["answer"]
    assert "custom_mass_rates" not in r["answer"]
    assert all("custom_mass_rates" not in s["source_ref"] for s in r["sources"])
    assert all("config/service_sources.yaml" not in s["source_ref"] for s in r["sources"])
    assert r["evidence_summary"]["MISSING"] == 2
    assert r["retrieval_trace"]["mass_t"] == 664.711


def test_custom_mass_followup_uses_previous_trace_for_height_work():
    trace = {
        "mode": "custom_mass_estimate_assumed",
        "mass_t": 664.711,
        "tiers": 11,
        "material_cost_zero": True,
        "transport_zero": True,
    }
    r = _answer_object_estimate(
        "учти высотные работы",
        context_questions=["Сколько стоит монтаж стальных ярусов?"],
        context_traces=[trace],
    )
    assert r is not None and r["operation"] == "custom_mass_estimate_assumed"
    assert "664.71 т" in r["answer"]
    assert "восстановлены из предыдущего расчёта" in r["answer"]
    assert "Высотные работы распознаны" in r["answer"]
    assert r["retrieval_trace"]["height_work"]["requested"] is True
    assert r["retrieval_trace"]["height_work"]["applied"] is False
    assert r["evidence_summary"]["MISSING"] == 3


def test_custom_mass_followup_applies_explicit_height_coefficient():
    trace = {
        "mode": "custom_mass_estimate_assumed",
        "mass_t": 664.711,
        "tiers": 11,
        "material_cost_zero": True,
        "transport_zero": True,
    }
    r = _answer_object_estimate("учти высотные работы k=1,15", context_traces=[trace])
    assert r is not None
    assert "коэффициентом k=1.15" in r["answer"]
    assert r["retrieval_trace"]["height_work"]["applied"] is True
    assert r["retrieval_trace"]["height_work"]["coefficient"] == 1.15
    assert r["evidence_summary"]["MISSING"] == 2
