"""Каркас router-бенча + constrained-output роутера. Без живого LLM (мок), без сети."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from proxy.services import agent_router_service as ar
from tools import router_bench as rb

CASES_PATH = Path("golden/router_eval_set.json")


# ── каталог инструментов ──

def test_catalog_registers_target_tools():
    names = set(ar._BY_NAME)
    expected = {
        "asbuilt", "les_md", "project_registry", "field", "task", "preset",
        "glossary", "price_lookup", "kac", "stesnennost", "lsr_assemble",
        "table_agg", "clause", "memory", "decision", "none",
    }
    assert expected <= names, f"не зарегистрированы: {expected - names}"


def test_every_tool_has_desc_and_examples():
    for t in ar._TOOLS:
        assert t["desc"].strip(), f"{t['name']}: пустое описание"
        # у всех кроме none — примеры-триггеры (по ним LLM выбирает)
        if t["name"] != "none":
            assert t.get("examples"), f"{t['name']}: нет примеров"
        assert "name" in t and "handler" in t


def test_prompt_has_catalog_and_fewshot():
    p = ar._build_prompt("сколько стоит 91.05.01-017")
    assert "price_lookup" in p and "none" in p          # каталог
    assert "Примеры:" in p and '"tool": "memory"' in p  # few-shot встроен


# ── constrained output: имя валидируется по каталогу ──

@pytest.mark.parametrize("raw,want", [
    ('{"tool": "price_lookup"}', "price_lookup"),
    ('price_lookup', "price_lookup"),
    ('{"tool": "search_web"}', "none"),       # выдуманный инструмент → none
    ('{"tool": ""}', "none"),                  # пусто → none
    ('бла-бла без имени', "none"),             # шум → none
    ('', "none"),                              # модель промолчала → none
])
def test_constrained_output_collapses_to_none(monkeypatch, raw, want):
    # роутер ходит в свой LLM-сем (_route_llm_text), не в les_md_service._llm_text — патчим его
    monkeypatch.setattr(ar, "_route_llm_text", lambda *a, **k: raw)
    assert ar._classify("любой запрос") == want


def test_hallucinated_tool_never_executes(monkeypatch):
    """Галлюцинация имени не должна звать никакой handler — уходит в RAG (None)."""
    monkeypatch.setenv("LES_AGENT_LOOP", "true")
    monkeypatch.setattr("proxy.services.les_md_service._llm_text",
                        lambda *a, **k: '{"tool": "delete_everything"}')
    assert ar.maybe_agent_route("что-нибудь") is None


# ── golden-набор ──

def test_golden_set_valid_and_references_known_tools():
    cases = rb.load_cases(CASES_PATH)
    assert len(cases) >= 25
    names = set(ar._BY_NAME)
    for c in cases:
        assert c.expected in names, f"{c.id}: неизвестный expected «{c.expected}»"
    # каждый интент покрыт; есть переформулировки и none-кейсы
    assert sum(1 for c in cases if c.rephrase) >= 10
    assert sum(1 for c in cases if c.expected == "none") >= 3


# ── каркас бенча (мок-классификатор) ──

def test_bench_perfect_with_truth_classifier():
    cases = rb.load_cases(CASES_PATH)
    classify = rb._self_test_classifier(cases)
    outcomes = rb.run(cases, classify)
    summary = rb.report(outcomes)
    assert summary["overall"] == 1.0
    assert summary["rephrase_acc"] == 1.0
    assert summary["misses"] == []


def test_bench_counts_misses_and_per_tool(capsys):
    cases = [
        rb.Case("a", "q1", "price_lookup", False),
        rb.Case("b", "q2", "price_lookup", True),
        rb.Case("c", "q3", "glossary", True),
    ]
    # классификатор «всё в glossary» → price 0/2, glossary 1/1
    summary = rb.report(rb.run(cases, lambda q: "glossary"))
    assert summary["overall_hits"] == 1 and summary["overall_n"] == 3
    assert summary["by_tool"]["price_lookup"] == 0.0
    assert summary["by_tool"]["glossary"] == 1.0
    assert len(summary["misses"]) == 2
    # промах price помечен и виден в выводе
    assert any(m["expected"] == "price_lookup" for m in summary["misses"])


def test_bench_self_test_cli_returns_zero():
    assert rb.main(["--cases", str(CASES_PATH), "--self-test"]) == 0
