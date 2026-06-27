"""W11.15 — сводка проекта (ТЭП/стадия/состав). Офлайн, без LLM."""

from __future__ import annotations

from pathlib import Path

from backend.parquet_writer import save_parquet
from proxy.services.project_summary_service import (
    build_project_summary,
    extract_tep,
    is_project_summary_query,
)


def _row(name, qty=None, unit="", doc_title="", section="", source="proj.xlsx", doc_type="TABLE"):
    base = {k: None for k in ("qty", "work_done", "work_since_start", "work_volume")}
    base.update({"doc_type": doc_type, "name": name, "unit": unit, "qty": qty,
                 "doc_title": doc_title, "section": section, "source_file": source})
    return base


# ── интент ──

def test_intent_positive():
    for q in ["Дай сводку проекта", "Покажи ТЭП котельной", "Технико-экономические показатели",
              "Что за проект, кратко о нём", "Сводка по объекту"]:
        assert is_project_summary_query(q), q


def test_intent_negative():
    for q in ["Сколько кабеля в смете", "Сверь ведомости и акты", "Какие требования к серверным"]:
        assert not is_project_summary_query(q), q


# ── ТЭП-экстрактор ──

def test_tep_from_indicator_names():
    rows = [
        _row("Тепловая мощность котельной", qty=10.5, unit="Гкал/ч"),
        _row("КПД котла", qty=92.0, unit="%"),
        _row("Кабель ВВГ 3х1,5", qty=744.0, unit="м"),  # не ТЭП
    ]
    tep = extract_tep(rows)
    names = {t["indicator"] for t in tep}
    assert "Тепловая мощность котельной" in names
    assert "КПД котла" in names
    assert "Кабель ВВГ 3х1,5" not in names


def test_tep_from_table_anchor():
    # вся таблица помечена как «Технико-экономические показатели» → строки = показатели
    rows = [
        _row("Площадь застройки", qty=320.0, unit="м2", doc_title="Технико-экономические показатели"),
        _row("Строительный объём", qty=4200.0, unit="м3", doc_title="Технико-экономические показатели"),
    ]
    tep = extract_tep(rows)
    assert len(tep) == 2


def test_stage_detection(tmp_path):
    pdir = tmp_path / "ds" / "_parquet"
    pdir.mkdir(parents=True)
    save_parquet([_row("Тепловая мощность", qty=10.0, unit="Гкал/ч",
                       source="Котельная_РД_ОВ.xlsx", doc_title="Рабочая документация")],
                 str(pdir / "p.parquet"))
    res = build_project_summary(["ds"], storage_root=tmp_path)
    assert "РД" in res["stage"]
    assert res["tep"] and res["tep"][0]["value"] == 10.0
    assert res["document_count"] == 1


def test_build_summary_no_tep(tmp_path):
    pdir = tmp_path / "ds" / "_parquet"
    pdir.mkdir(parents=True)
    save_parquet([_row("Болт М10", qty=50.0, unit="шт", source="spec.xlsx")], str(pdir / "p.parquet"))
    res = build_project_summary(["ds"], storage_root=tmp_path)
    assert res["tep"] == []  # ничего ТЭП-подобного
    assert res["stage"] == "не определена"


def test_uses_no_llm():
    import inspect

    import proxy.services.project_summary_service as svc

    src = inspect.getsource(svc)
    for marker in ("import httpx", "import openai", "/api/chat", "completions"):
        assert marker not in src
