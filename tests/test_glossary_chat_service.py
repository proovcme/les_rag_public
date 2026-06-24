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


# ── v0.18 регресс: предлог «на» не резолвится в ОЖР, нарратив про объект → не глоссарий ──────

def test_stopword_na_does_not_resolve_to_ozr():
    from proxy.services import glossary_chat_service as g
    assert g._resolve("на") is None
    assert g._resolve("котельную на лесном 64") is None

def test_narrative_about_object_not_hijacked_by_glossary():
    from proxy.services.glossary_chat_service import maybe_handle_glossary_query
    # «расскажи про котельную на лесном 64» — нарратив про объект → RAG, НЕ определение ОЖР
    assert maybe_handle_glossary_query("Расскажи про котельную на лесном 64?") is None
    assert maybe_handle_glossary_query("расскажи про объект на участке") is None

def test_real_glossary_terms_still_resolve():
    from proxy.services.glossary_chat_service import maybe_handle_glossary_query as h
    assert h("что такое КАЦ")["concept"] == "kac"
    assert h("что такое ЛСР")["concept"] == "lsr"
    assert h("что такое ВОР")["concept"] == "vor"
    assert h("что такое ОЖР")["concept"] == "ozr"
    assert h("расскажи про КАЦ")["concept"] == "kac"   # «расскажи про <термин>» — валидное определение
