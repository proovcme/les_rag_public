"""Harvest-петля: verify-записи → train-set + таксономия ошибок (pred→target)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proxy.services import harvest_service as hs
from proxy.services import verify_service
from proxy.services.harvest_service import (
    build_training_set,
    classify_cell,
    error_taxonomy,
)


@pytest.fixture()
def fake_verifs(tmp_path: Path, monkeypatch) -> Path:
    verifs = tmp_path / "verifications"
    cache = tmp_path / "verify_cache"
    verifs.mkdir()
    cache.mkdir()
    monkeypatch.setattr(verify_service, "VERIFY_DIR", verifs)
    monkeypatch.setattr(verify_service, "CACHE_DIR", cache)

    def _write(token, rec, with_img=True):
        (verifs / f"{token}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        if with_img:
            (cache / f"{token}.png").write_bytes(b"\x89PNG\r\n")

    # принято как есть (без pred)
    _write("t1", {"token": "t1", "source": "a.pdf", "page": 0, "verdict": "ok",
                  "rows": [{"Код": "01.1", "Кол-во": "5"}], "pred_rows": None})
    # исправлено: «S»→«5» (char_confusion) + потеряна строка (missing_row)
    _write("t2", {"token": "t2", "source": "b.pdf", "page": 1, "verdict": "corrected",
                  "rows": [{"Код": "01.2", "Кол-во": "5"}, {"Код": "01.3", "Кол-во": "10"}],
                  "pred_rows": [{"Код": "01.2", "Кол-во": "S"}]})
    # отклонено — не таблица; в train и таксономию не идёт
    _write("t3", {"token": "t3", "source": "c.pdf", "page": 0, "verdict": "rejected",
                  "rows": [], "pred_rows": None}, with_img=False)
    return tmp_path


def test_classify_cell_classes():
    assert classify_cell("5", "5") is None
    assert classify_cell("S", "5") == "char_confusion"
    assert classify_cell("О", "0") == "char_confusion"   # кириллица О → ноль
    assert classify_cell("10", "12") == "numeric_value"
    assert classify_cell("Бетон", "бетон") == "whitespace_case"   # отличие только регистром
    assert classify_cell("а  б", "а б") == "whitespace_case"       # внутренние пробелы
    assert classify_cell("", "пол") == "empty_pred"


def test_build_training_set(fake_verifs: Path, tmp_path: Path):
    out = tmp_path / "train"
    manifest = build_training_set(out)
    assert manifest["samples"] == 2                       # ok + corrected, rejected отброшен
    assert manifest["by_verdict"] == {"ok": 1, "corrected": 1, "rejected": 1}
    assert manifest["with_image"] == 2
    assert manifest["with_pred_rows"] == 1
    lines = (out / "dataset.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["image"] and rec["target_rows"]


def test_error_taxonomy_detects_systematic(fake_verifs: Path):
    tax = error_taxonomy()
    assert tax["corrected_records"] == 1
    assert tax["analyzed"] == 1
    assert tax["skipped_no_pred"] == 0
    assert tax["by_class"].get("char_confusion", 0) >= 1
    assert tax["by_class"].get("missing_row", 0) >= 1
