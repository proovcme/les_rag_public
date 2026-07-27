"""Smeta chat channel: only code-based quick tools, never object compositions."""

from __future__ import annotations

from proxy.services import fgis_price_service as fps
from proxy.services.smeta_chat_service import maybe_handle_smeta_query as h


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


def test_assemble_from_code_reproduces_etalon():
    r = h("собери ГЭСН12-01-034-02 объём 61 м2")
    assert r is not None and r["operation"] == "assemble"
    assert "11 813.04" in r["answer"]


def test_assemble_does_not_guess_stesnennost_from_phrase():
    r = h("собери ГЭСН12-01-034-02 объём 61 м2 стеснённость город")
    assert r["operation"] == "assemble"
    assert "11 813.04" in r["answer"]
    assert "13 572.45" not in r["answer"]


def test_assemble_needs_volume():
    r = h("собери ГЭСН12-01-034-02")
    assert r["operation"] == "assemble" and "объём" in r["answer"].lower()


def test_non_smeta_falls_through():
    assert h("привет как дела") is None
    assert h("посчитай смету") is None
    assert h("") is None


def test_object_and_mass_estimates_do_not_use_quick_smeta_channel():
    assert h("посчитай смету на дом 150 м2") is None
    assert h("дай смету на бетонную дачу 300 метров") is None
    assert h("стальные ярусы масса 664 711 кг, учти высотные работы") is None
