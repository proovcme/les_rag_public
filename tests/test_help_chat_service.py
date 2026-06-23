"""Чат-канал «помощь»: справочник промтов в чате (обзор + тематические срезы)."""

from __future__ import annotations

from proxy.services.help_chat_service import maybe_handle_help_query as h


def test_overview():
    r = h("что ты умеешь")
    assert r is not None and r["operation"] == "help"
    assert "СМЕТА" in r["answer"] and "ДОКУМЕНТЫ" in r["answer"]
    assert h("помощь")["operation"] == "help"


def test_topic_slices():
    assert "цена 91.05" in h("как спросить про смету")["answer"]
    assert "КОНКРЕТ" in h("как спрашивать про документы")["answer"].upper()
    assert "реестр" in h("примеры вопросов по объектам")["answer"]


def test_does_not_hijack_other_channels():
    assert h("цена 91.05.01-017") is None        # → smeta
    assert h("что такое КАЦ") is None             # → glossary
    assert h("привет") is None
    assert h("") is None
