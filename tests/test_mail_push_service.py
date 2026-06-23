"""Маршрутизация письма из Outlook-плагина: классификация вложений + КП→КАЦ. Без сети."""

from __future__ import annotations

import base64
from pathlib import Path

from proxy.services import mail_push_service as mps


def test_classify_attachment():
    assert mps.classify_attachment("КП_Гранит_2024.pdf") == "kp"
    assert mps.classify_attachment("Прайс-лист.pdf") == "kp"
    assert mps.classify_attachment("Смета_объект.xlsx") == "estimate"
    assert mps.classify_attachment("ВОР раздел 5.pdf") == "estimate"
    assert mps.classify_attachment("scan_akt_0012.jpg") == "scan"
    assert mps.classify_attachment("Договор.pdf") == "doc"


def test_save_attachments_decodes_and_dedups(tmp_path: Path):
    b64 = base64.b64encode(b"hello").decode()
    atts = [{"name": "КП_Лев.pdf", "content_b64": b64},
            {"name": "КП_Лев.pdf", "content_b64": b64}]   # одноимённые → не перезатереть
    saved = mps.save_attachments(atts, tmp_path / "m1")
    assert len(saved) == 2
    assert saved[0]["kind"] == "kp" and saved[0]["size"] == 5
    assert len({Path(s["path"]).name for s in saved}) == 2


def test_save_attachments_bad_b64_does_not_raise(tmp_path: Path):
    saved = mps.save_attachments([{"name": "x.pdf", "content_b64": "!!not base64!!"}], tmp_path / "m2")
    assert len(saved) == 1 and Path(saved[0]["path"]).exists()


def test_route_push_kp_triggers_kac(tmp_path: Path, monkeypatch):
    called: dict = {}

    def fake_analyze(paths, **kw):
        called["paths"] = list(paths)
        return {"ok": True, "winner": {"price": 2300, "supplier": "LEV"}}

    monkeypatch.setattr("proxy.services.kac_pdf_service.extract_and_analyze", fake_analyze)
    saved = [
        {"name": "КП_A.pdf", "path": str(tmp_path / "a.pdf"), "kind": "kp", "size": 10},
        {"name": "смета.xlsx", "path": str(tmp_path / "s.xlsx"), "kind": "estimate", "size": 10},
    ]
    plan = mps.route_push(saved)
    assert plan["kp_count"] == 1 and called["paths"] == [str(tmp_path / "a.pdf")]
    assert plan["kac"]["ok"] is True and plan["kac"]["winner"]["price"] == 2300
    assert len(plan["to_rag"]) == 1                      # смета уходит в RAG
    dests = {r["kind"]: r["destination"] for r in plan["routed"]}
    assert "КАЦ" in dests["kp"]


def test_route_push_no_kp_no_kac():
    plan = mps.route_push([{"name": "d.pdf", "path": "x", "kind": "doc", "size": 1}])
    assert plan["kac"] is None and plan["kp_count"] == 0


def test_email_as_text_has_header():
    t = mps.email_as_text("Тема1", "ivan@x.ru", "2026-06-23", "Привет")
    assert "Тема: Тема1" in t and "От: ivan@x.ru" in t and t.endswith("Привет")
