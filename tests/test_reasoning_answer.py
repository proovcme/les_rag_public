"""#1 (Windows ollama): извлечение ответа у reasoning-моделей.

qwen3.5:9b (и о-серия) кладут финальный ответ в `content`, а размышления — в
`reasoning`/`reasoning_content` и/или `<think>…</think>`. Пока модель «думает», content пуст
(`finish_reason=length`) → раньше ЛЕС отдавал пустой ответ. `_assistant_text` берёт content без
think-блоков, а при пустом content — fallback на reasoning. Не-reasoning модели не затронуты.
"""

from proxy.routers.chat import _assistant_text, _strip_think


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
