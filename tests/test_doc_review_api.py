"""Тест doc-review API (СПДС-нормоконтроль, Phase 4): rulepacks-эндпоинт + run-обёртка.
Логика review — в doc_review_service (там тесты); здесь — что роутер корректно её зовёт и честно
отдаёт 404 на пустой датасет (не fake-результат)."""

import asyncio

import pytest
from fastapi import HTTPException

from proxy.routers import doc_review as drv
from proxy.routers.doc_review import (
    DocReviewDecisionRequest,
    DocReviewRequest,
    doc_review_decisions,
    doc_review_rulepacks,
    doc_review_run,
    doc_review_set_decision,
)


def test_rulepacks_lists_gost():
    out = asyncio.run(doc_review_rulepacks(_user=object()))
    names = [r.get("name") for r in out["rulepacks"]]
    assert "gost_r_21_101_2026" in names
    gost = next(r for r in out["rulepacks"] if r["name"] == "gost_r_21_101_2026")
    assert gost["standard"] == "ГОСТ Р 21.101-2026"
    assert gost["targets"] >= 10


def test_run_empty_dataset_is_404():
    # несуществующий датасет → 404 (нет документов), а не пустой fake-отчёт
    with pytest.raises(HTTPException) as exc:
        asyncio.run(doc_review_run("no-such-dataset-xyz", DocReviewRequest(), _user=object()))
    assert exc.value.status_code == 404


def test_request_defaults():
    r = DocReviewRequest()
    assert r.rulepack == "gost_r_21_101_2026"
    assert r.mode == "rag_review"
    assert r.strictness == "normal"


def test_decision_endpoint_persists_engineer_choice(tmp_path, monkeypatch):
    monkeypatch.setattr(drv, "_OUT_DIR", tmp_path)
    req = DocReviewDecisionRequest(rule_id="G21.101-2026-D1-011", decision="rejected", comment="Не применимо к комплекту")
    out = asyncio.run(doc_review_set_decision("BAI", req, _user=object()))
    assert out["ok"] is True
    saved = asyncio.run(doc_review_decisions("BAI", _user=object()))
    item = saved["decisions"]["G21.101-2026-D1-011"]
    assert item["decision"] == "rejected"
    assert item["comment"] == "Не применимо к комплекту"


def test_decision_endpoint_rejects_bad_value(tmp_path, monkeypatch):
    monkeypatch.setattr(drv, "_OUT_DIR", tmp_path)
    req = DocReviewDecisionRequest(rule_id="G21.101-2026-D1-011", decision="final_verdict")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(doc_review_set_decision("BAI", req, _user=object()))
    assert exc.value.status_code == 400
