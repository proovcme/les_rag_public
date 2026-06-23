"""Голос Совушки в детерминированных каналах: рамка поверх фактов + обход к модели."""

from __future__ import annotations

from proxy.services.glossary_chat_service import maybe_handle_glossary_query
from proxy.services.smeta_chat_service import maybe_handle_smeta_query
from proxy.services import sovushka_tone as tone


def test_flavor_wraps_but_keeps_facts():
    out = tone.flavor("КАЦ — конъюнктурный анализ цен", "glossary", seed="кац")
    assert "КАЦ — конъюнктурный анализ цен" in out      # факт цел
    assert out != "КАЦ — конъюнктурный анализ цен"        # есть рамка
    assert "\n" in out
    # неизвестный тип → без рамки
    assert tone.flavor("X", "нет-такого") == "X"


def test_flavor_is_stable():
    a = tone.flavor("Y", "price", seed="91.05.01-017")
    b = tone.flavor("Y", "price", seed="91.05.01-017")
    assert a == b                                          # детерминировано (тестируемо)


def test_wants_model_bypass():
    assert tone.wants_model("что такое КАЦ своими словами") is True
    assert tone.wants_model("поговорим про смету") is True
    assert tone.wants_model("что такое КАЦ") is False


def test_bypass_lets_channels_yield_to_model():
    # явное «к модели» → каналы возвращают None (вопрос уходит в RAG/LLM, не в справочник)
    assert maybe_handle_glossary_query("что такое КАЦ своими словами") is None
    assert maybe_handle_smeta_query("цена 91.05.01-017, но ответь своими словами") is None
    # без обхода — канал отвечает (с голосом)
    g = maybe_handle_glossary_query("что такое КАЦ")
    assert g is not None and "конъюнктурный" in g["answer"].lower()
