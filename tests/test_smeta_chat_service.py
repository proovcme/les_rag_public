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
    assert "ASSUME" in r["answer"]
    assert r["evidence_summary"]["MISSING"] == 2
    assert r["retrieval_trace"]["mass_t"] == 664.711
