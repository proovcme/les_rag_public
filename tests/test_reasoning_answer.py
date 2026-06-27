"""#1 (Windows ollama): извлечение ответа у reasoning-моделей.

qwen3.5:9b (и о-серия) кладут финальный ответ в `content`, а размышления — в
`reasoning`/`reasoning_content` и/или `<think>…</think>`. Пока модель «думает», content пуст
(`finish_reason=length`) → раньше ЛЕС отдавал пустой ответ. `_assistant_text` берёт content без
think-блоков, а при пустом content — fallback на reasoning. Не-reasoning модели не затронуты.
"""

from proxy.routers.chat import (
    _assistant_text,
    _ollama_native_body,
    _ollama_native_url,
    _strip_think,
)


def test_plain_content_unchanged():
    # не-reasoning модель: content есть → возвращается как был
    assert _assistant_text({"content": "Привет, это ответ."}) == "Привет, это ответ."


def test_empty_content_falls_back_to_reasoning():
    # ровно случай ollama qwen3.5: content пуст, текст в reasoning
    msg = {"content": "", "reasoning": "Thinking Process: ответ — да."}
    assert _assistant_text(msg) == "Thinking Process: ответ — да."


def test_reasoning_content_alt_key():
    assert _assistant_text({"content": "", "reasoning_content": "альт-поле"}) == "альт-поле"


def test_inline_think_stripped_keeps_answer():
    msg = {"content": "<think>прикидываю варианты</think>Итог: 1,2 м."}
    assert _assistant_text(msg) == "Итог: 1,2 м."


def test_content_wins_over_reasoning():
    # если есть и то и то — берём content (финальный ответ), reasoning игнорим
    msg = {"content": "финал", "reasoning": "длинные размышления"}
    assert _assistant_text(msg) == "финал"


def test_content_only_think_then_reasoning_fallback():
    # content состоит ТОЛЬКО из think-блока → после среза пуст → fallback на reasoning
    msg = {"content": "<think>...</think>", "reasoning": "резервный текст"}
    assert _assistant_text(msg) == "резервный текст"


def test_non_dict_and_empty_safe():
    assert _assistant_text(None) == ""
    assert _assistant_text({}) == ""
    assert _assistant_text({"content": None, "reasoning": None}) == ""


def test_strip_think_multiline_and_case():
    assert _strip_think("a<THINK>\nx\ny\n</THINK>b") == "ab"
    assert _strip_think("чистый текст") == "чистый текст"


# ── #1b: нативный ollama /api/chat think:false (чистый ответ reasoning-моделей) ──

def test_ollama_native_url_strips_v1_and_appends_api_chat():
    assert _ollama_native_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434/api/chat"
    assert _ollama_native_url("http://127.0.0.1:11434/") == "http://127.0.0.1:11434/api/chat"
    # base мог быть задан с /v1 (OpenAI-compat) — для нативного эндпоинта срезаем
    assert _ollama_native_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/api/chat"
    assert _ollama_native_url("http://127.0.0.1:11434/v1/") == "http://127.0.0.1:11434/api/chat"
    assert _ollama_native_url("") == "http://127.0.0.1:11434/api/chat"


def test_ollama_native_body_disables_thinking_by_default():
    msgs = [{"role": "user", "content": "привет"}]
    b = _ollama_native_body("qwen3.5:9b", msgs, max_tokens=512, temperature=0.7, stream=False)
    assert b["think"] is False                 # ключ фикса: без размышлений → чистый content
    assert b["model"] == "qwen3.5:9b"
    assert b["messages"] is msgs
    assert b["stream"] is False
    assert b["options"] == {"num_predict": 512, "temperature": 0.7}


def test_ollama_native_body_stream_and_think_flag():
    b = _ollama_native_body("m", [], max_tokens=10, temperature=0.0, stream=True, think=True)
    assert b["stream"] is True and b["think"] is True


def test_assistant_text_parses_native_message_shape():
    # нативный ответ ollama: {"message": {"content": ...}} — think:false → content чист
    assert _assistant_text({"content": "Нет, я в облаке."}) == "Нет, я в облаке."
