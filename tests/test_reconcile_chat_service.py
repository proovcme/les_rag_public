"""W11.4b — сверка как задача чата. Офлайн: интент + полный цикл на синтетике Parquet."""

from __future__ import annotations

from pathlib import Path

from backend.parquet_writer import save_parquet
from proxy.services.reconcile_chat_service import (
    answer_reconcile_query,
    find_parquet_dataset_ids,
    is_reconcile_query,
)


# ── интент ──

def test_intent_positive():
    for q in [
        "Сверь ВОР и КС-2",
        "Сходятся ли объёмы в смете и КС-2?",
        "Проверь соответствие сметы и ведомости",
        "Есть ли расхождения по количеству позиций?",
        "Сверка ВОР со сметой",
    ]:
        assert is_reconcile_query(q), q


def test_intent_negative():
    for q in [
        "Какие требования к серверным?",      # норматив, не сверка
        "Сколько кабеля в смете?",            # агрегат, не сверка
        "Соответствует ли проект современным трендам?",  # «соответству» без контекста док-тов? есть «проект»? нет в контексте
        "Расскажи про эвакуацию",
    ]:
        assert not is_reconcile_query(q), q


# ── обнаружение датасетов с Parquet ──

def _mk(tmp_path, ds_id, rows):
    pdir = tmp_path / ds_id / "_parquet"
    pdir.mkdir(parents=True)
    full = []
    for r in rows:
        base = {k: None for k in ("qty", "work_done", "work_since_start", "work_volume")}
        base.update({"doc_type": "", "name": "", "unit": "", "source_file": "x.xlsx"})
        base.update(r)
        full.append(base)
    save_parquet(full, str(pdir / f"{ds_id}.parquet"))


def test_find_parquet_datasets(tmp_path):
    _mk(tmp_path, "ds_a", [{"doc_type": "SMETA", "name": "X", "qty": 1.0}])
    (tmp_path / "ds_empty").mkdir()  # без _parquet — игнор
    ids = find_parquet_dataset_ids(tmp_path)
    assert ids == ["ds_a"]


# ── полный цикл ──

def test_answer_reports_mismatch(tmp_path):
    _mk(tmp_path, "smeta", [{"doc_type": "SMETA", "name": "Лоток кабельный", "unit": "м", "qty": 100.0}])
    _mk(tmp_path, "ks2", [{"doc_type": "KS2", "name": "Лоток кабельный", "unit": "м", "work_done": 85.0}])
    res = answer_reconcile_query("сверь смету и кс-2", storage_root=tmp_path)
    assert res is not None
    assert res["has_issues"] is True
    assert res["totals"]["mismatch"] == 1
    assert "Расхождения" in res["answer"]
    assert "Лоток кабельный" in res["answer"]


def test_answer_single_doctype_explains(tmp_path):
    _mk(tmp_path, "vor", [{"doc_type": "VEDOMOST", "name": "Кабель", "unit": "м", "qty": 5.0}])
    res = answer_reconcile_query("сходятся ли объёмы?", storage_root=tmp_path)
    assert res is not None
    assert res["totals"]["single"] == 1
    assert "один тип документа" in res["answer"]


def test_answer_none_when_no_parquet(tmp_path):
    assert answer_reconcile_query("сверь вор и кс-2", storage_root=tmp_path) is None


def test_explicit_scope_filters_to_existing_parquet(tmp_path):
    _mk(tmp_path, "smeta", [{"doc_type": "SMETA", "name": "Розетка 220В", "unit": "шт", "qty": 1.0}])
    _mk(tmp_path, "ks2", [{"doc_type": "KS2", "name": "Розетка 220В", "unit": "шт", "qty": 1.0}])
    # scope только на smeta → один источник → single
    res = answer_reconcile_query("сверь", storage_root=tmp_path, dataset_ids=["smeta"])
    assert res["dataset_ids"] == ["smeta"]
    assert res["totals"]["single"] == 1


def test_uses_no_llm():
    import inspect

    import proxy.services.reconcile_chat_service as rc

    src = inspect.getsource(rc)
    for marker in ("import httpx", "import openai", "/api/chat", "completions"):
        assert marker not in src
