"""Чат-канал «смета»: цена по коду / нужен ли КАЦ / коэф. стеснённости (0 LLM, до RAG)."""

from __future__ import annotations

from proxy.services import fgis_price_service as fps
from proxy.services.smeta_chat_service import maybe_handle_smeta_query as h


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
