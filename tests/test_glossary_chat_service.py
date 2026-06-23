"""Чат-канал глоссария: «что такое X» → определение из онтологии (0 LLM)."""

from __future__ import annotations

from proxy.services.glossary_chat_service import maybe_handle_glossary_query as h


def test_definition_questions_resolve():
    r = h("Что такое КАЦ в смете и из чего он формируется?")
    assert r is not None and r["concept"] == "kac"
    assert "конъюнктурный" in r["answer"].lower()
    assert r["operation"] == "glossary"
    assert h("расскажи про ВОР")["concept"] == "vor"
    assert h("что значит стеснённость")["concept"] == "coef_stesn"
    assert h("дай определение ЛСР")["concept"] == "lsr"


def test_non_glossary_falls_through():
    assert h("сколько кабеля в смете") is None      # не вопрос-определение
    assert h("привет, как дела") is None
    assert h("что такое квазар") is None             # нет в онтологии → None (уходит в RAG)
    assert h("") is None
