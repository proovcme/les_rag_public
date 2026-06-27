"""help-канал — ИНСТРУМЕНТ, не keyword-гейт на понимание (docs/AUDIT_DETERMINISM).

Регресс: «расскажи всё что можешь про объект» сматчился по подстроке «что можешь» → help
выдал список команд вместо ответа про объект. Теперь help срабатывает ТОЛЬКО когда сам запрос
И ЕСТЬ просьба о помощи (лидирующий триггер ≈ всё сообщение), а содержательный вопрос уходит в RAG.
"""
from __future__ import annotations

import pytest

from proxy.services.help_chat_service import maybe_handle_help_query as _help


@pytest.mark.parametrize("q", [
    "расскажи всё что можешь про объект",   # «что можешь» в середине — это про объект, не справка
    "что можешь рассказать про смету?",
    "расскажи про Байконур",
    "опиши проект",
    "какие системы на объекте",
])
def test_content_question_is_not_help(q):
    assert _help(q) is None, f"содержательный вопрос ушёл в help: {q!r}"


@pytest.mark.parametrize("q", [
    "помощь",
    "что умеешь?",
    "что ты можешь?",
    "как спрашивать",
    "help",
])
def test_explicit_help_request_is_help(q):
    r = _help(q)
    assert r is not None and r.get("operation") == "help", f"явная просьба о помощи не дала help: {q!r}"
