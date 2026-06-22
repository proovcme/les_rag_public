"""Offline tests for manual-verification backend (no model, no display)."""

from __future__ import annotations

import json
from pathlib import Path

from proxy.services import verify_service as vs


def test_token_stable_and_unique():
    assert vs._token("a.pdf", 1) == vs._token("a.pdf", 1)
    assert vs._token("a.pdf", 1) != vs._token("a.pdf", 2)
    assert vs._token("a.pdf", 1) != vs._token("b.pdf", 1)


def test_save_get_list_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(vs, "VERIFY_DIR", tmp_path / "ver")
    rec = vs.save_verification("scan.pdf", 1, [{"поз": 1, "объём": "5"}], "corrected")
    assert rec["verdict"] == "corrected" and rec["page"] == 1

    got = vs.get_verification("scan.pdf", 1)
    assert got["rows"] == [{"поз": 1, "объём": "5"}]
    assert got["source"] == "scan.pdf"

    items = vs.list_verifications()
    assert len(items) == 1 and items[0]["n_rows"] == 1 and items[0]["verdict"] == "corrected"

    assert vs.get_verification("scan.pdf", 2) is None  # другая страница — нет записи


def test_render_and_extract_orchestration(monkeypatch, tmp_path):
    from proxy.services import asbuilt_ocr

    class _FakeImg:
        width, height = 100, 200

        def save(self, p):
            Path(p).write_bytes(b"\x89PNG-stub")

    monkeypatch.setattr(vs, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(vs, "_safe_path", lambda path: tmp_path / "scan.pdf")
    monkeypatch.setattr(vs, "_load_page_image", lambda src, page: _FakeImg())
    # vision дал пусто → результат пустой (фолбэка на gemma больше нет), но скан закэширован
    monkeypatch.setattr(vs, "_vision_extract_rows", lambda image: [])

    res = vs.render_and_extract("scan.pdf", 0, "local")
    assert res["rows"] == [] and res["columns"] == []
    # рендер страницы закэширован и достаётся по токену — оператор заполнит вручную
    assert vs.image_path(res["token"]) is not None


def test_render_and_extract_uses_vision_first(monkeypatch, tmp_path):
    class _FakeImg:
        width, height = 100, 200

        def save(self, p, **kw):
            from pathlib import Path
            Path(p).write_bytes(b"x") if isinstance(p, (str, Path)) else None

    monkeypatch.setattr(vs, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(vs, "_safe_path", lambda path: tmp_path / "scan.pdf")
    monkeypatch.setattr(vs, "_load_page_image", lambda src, page: _FakeImg())
    monkeypatch.setattr(vs, "_vision_extract_rows", lambda image: [{"помещение": "451", "количество": "5"}])

    res = vs.render_and_extract("scan.pdf", 0, "local")
    assert res["rows"] == [{"помещение": "451", "количество": "5"}]
    assert res["columns"] == ["помещение", "количество"]


def test_render_and_extract_survives_failed_extraction(monkeypatch, tmp_path):
    from proxy.services import asbuilt_ocr

    class _FakeImg:
        width, height = 100, 200

        def save(self, p):
            Path(p).write_bytes(b"x")

    monkeypatch.setattr(vs, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(vs, "_safe_path", lambda path: tmp_path / "scan.pdf")
    monkeypatch.setattr(vs, "_load_page_image", lambda src, page: _FakeImg())

    def _boom(*a, **k):
        raise RuntimeError("движок недоступен")

    monkeypatch.setattr(vs, "_vision_extract_rows", _boom)  # vision упал
    monkeypatch.setattr(asbuilt_ocr, "resolve_engine", _boom)  # и as-built упал
    res = vs.render_and_extract("scan.pdf", 0, "local")
    # оба движка упали → пустая таблица, но картинка есть, оператор заполнит руками
    assert res["rows"] == [] and res["columns"] == []
    assert vs.image_path(res["token"]) is not None


def test_big_sheet_requires_region(monkeypatch, tmp_path):
    # большой лист-чертёж без региона → не гоняем vision по всему листу, просим рамку
    class _BigImg:
        width, height = 5000, 3000  # 15 Мп > порога 12

        def save(self, p):
            Path(p).write_bytes(b"x")

    monkeypatch.setattr(vs, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(vs, "_safe_path", lambda path: tmp_path / "scan.pdf")
    monkeypatch.setattr(vs, "_load_page_image", lambda src, page: _BigImg())
    called = {"vision": False}

    def _v(image):
        called["vision"] = True
        return []

    monkeypatch.setattr(vs, "_vision_extract_rows", _v)
    res = vs.render_and_extract("scan.pdf", 0, "local")  # без региона
    assert res["needs_region"] is True and res["rows"] == []
    assert called["vision"] is False  # vision НЕ вызывали — мгновенно


def test_region_image_rejects_tiny_selection(tmp_path):
    # вырожденное/крошечное выделение → ошибка (а не пустой/мусорный кроп)
    import pytest
    with pytest.raises(ValueError):
        vs._region_image(tmp_path / "x.pdf", 0, [0.5, 0.5, 0.505, 0.505])


def test_render_and_extract_uses_region(monkeypatch, tmp_path):
    class _FakeImg:
        width, height = 100, 200

        def save(self, p):
            Path(p).write_bytes(b"x")

    monkeypatch.setattr(vs, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(vs, "_safe_path", lambda path: tmp_path / "scan.pdf")
    monkeypatch.setattr(vs, "_load_page_image", lambda src, page: _FakeImg())
    seen = {}

    def _region(src, page, region):
        seen["region"] = region
        return _FakeImg()

    monkeypatch.setattr(vs, "_region_image", _region)
    monkeypatch.setattr(vs, "_vision_extract_rows", lambda image: [{"кол": "5"}])

    res = vs.render_and_extract("scan.pdf", 0, "local", region=[0.1, 0.2, 0.8, 0.6])
    assert seen["region"] == [0.1, 0.2, 0.8, 0.6]  # регион ушёл в _region_image
    assert res["rows"] == [{"кол": "5"}] and res["img_w"] == 100 and res["img_h"] == 200


def test_router_imports_and_registered():
    from proxy.routers import verify as verify_router
    assert verify_router.router.prefix == "/api/verify"
    import proxy.app  # noqa: F401  — verify_router включён в include_router


def test_chat_verify_intent():
    from sovushka.pages.chat import _is_verify_request, _verify_path, _verify_page

    # путь с пробелами (реальные имена чек-листов) вытаскивается целиком
    q = "проверь объёмы /Users/ovc/RAG/Чек-листы оставшиеся/Чек-лист щиты.pdf стр 2"
    assert _verify_path(q) == "/Users/ovc/RAG/Чек-листы оставшиеся/Чек-лист щиты.pdf"
    assert _verify_page(q) == 1  # 1-based → 0-based
    assert _is_verify_request(q) is True
    assert _is_verify_request("сверь скан \"/a/b.png\"") is True
    # без пути или без verify-ключа — не перехватываем (обычный чат идёт в LLM)
    assert _is_verify_request("проверь почту") is False
    assert _is_verify_request("сколько объёмов за июнь?") is False
