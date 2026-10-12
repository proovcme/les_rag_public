"""Формирование ответа по интенту — ADR-12, слой 2 (W11.5).

Форму ответа диктует **тип вопроса**, детерминированно, ДО генерации. LLM лишь
наполняет заданный каркас. Здесь — pure-классификатор интента по KOT-словарю и
соответствующая добавка в системный промпт + потолок токенов под форму. Без LLM.

Интенты (ADR-12 §2):
- ``value`` — «да/нет / какое значение / ширина» → одна строка + ссылка на пункт;
- ``enum``  — «состав / перечень разделов» → голый список;
- ``full``  — «собери всё / подробно» → развёрнуто по разделам;
- ``brief`` — явный запрос краткости → сжатый перечень «пункт — строка сути»;
- ``default`` — интент не распознан, форму не навязываем (поведение модели как было).
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

# Порядок проверки — от самого специфичного интента к общему.
# «Значение/да-нет» (самый узкий ответ).
_VALUE_TOKENS = (
    "какое значение", "какова ширина", "какова высота", "чему равн", "на каком расстояни",
    "минимальн", "какой максимальн", "какая максимальн", "какое максимальн", "какова максимальн",
    "минимально допустим", "максимально допустим",
    "допустимо ли", "допускается ли", "можно ли", "нужно ли", "требуется ли", "обязательно ли",
    "да или нет", "сколько", "какая ширина", "какой размер", "какова площадь", "какой уклон",
)
# «Перечень/состав» (голый список).
_ENUM_TOKENS = (
    "перечисли", "перечень", "состав ", "список", "номенклатур", "какие разделы",
    "из чего состоит", "что входит", "какие документы", "какие позиции",
)
# «Собери всё/подробно» (развёрнуто).
_FULL_TOKENS = (
    "собери все", "собери всё", "подробно", "максимально подроб", "развернут", "развёрнут",
    "детально", "всё что", "все что есть", "полный обзор", "полностью опиши", "исчерпыва",
    "инженерный обзор", "технические решения", "что не сход", "что не так",
    "требует проверки", "разночтени",
)
# Явная краткость. Само по себе «расскажи» — широкий запрос, не команда резать ответ.
_BRIEF_TOKENS = (
    "кратко", "вкратце", "в двух словах", "суть ", "главное о",
)


@dataclass(frozen=True)
class AnswerForm:
    intent: str
    instruction: str   # добавка-каркас к системному промпту ("" — не навязываем форму)
    max_tokens: int    # потолок генерации под форму


_VALUE = AnswerForm(
    "value",
    "Форма ответа: ОДНА строка с конкретным значением/ответом и ссылкой на пункт нормы "
    "в скобках (например: «не менее 1,2 м (СП 1.13130, п. 4.3.4)»). Без вступления, без "
    "рассуждений, без закрывающих фраз. Если в контексте значения нет — так и скажи одной строкой.",
    256,
)
_ENUM = AnswerForm(
    "enum",
    "Форма ответа: голый маркированный список, без вступления и заключения. Каждый пункт — "
    "одна короткая строка. Не нумеруй прозой, не добавляй обрамляющий текст.",
    1024,
)
_FULL = AnswerForm(
    "full",
    "Форма ответа: развёрнуто, но без простыни. Структурируй по коротким разделам. "
    "Для обзорных инженерных ответов предпочитай списки и короткие абзацы; markdown-таблицы "
    "используй только для небольших сравнений, не превращай весь ответ в таблицу. "
    "Если вопрос просит инженерный обзор/технические решения/что не сходится, обязательно "
    "используй порядок: 1) паспорт объекта; 2) ключевые технические решения; "
    "3) важные файлы/разделы; 4) несостыковки и что проверить; 5) детали, если осталось место. "
    "Раздел 4 обязателен: если явных противоречий нет в контексте, назови зоны проверки "
    "и какие первоисточники открыть. Детали перечисляй сжато; не трать весь лимит на один раздел. "
    "Каждое важное число/утверждение — со ссылкой на источник/пункт.",
    3072,
)
_BRIEF = AnswerForm(
    "brief",
    "Форма ответа: сжатый перечень в виде «пункт нормы — одна строка сути». Без вступлений и "
    "закрывающих фраз, только суть. Указывай источник/пункт у каждого требования.",
    1024,
)
_DEFAULT = AnswerForm("default", "", 8192)   # снят блок длины по умолчанию (было 2048) — не режем ответ

_RESPONSE_LENGTHS: dict[str, tuple[int, str]] = {
    "short": (1024, "Пользователь выбрал короткий ответ: дай только вывод и необходимое обоснование."),
    # Standard intentionally preserves the previously successful default ceiling.
    "standard": (8192, "Пользователь выбрал обычную длину: ответь достаточно полно, без лишнего повторения."),
    "detailed": (12288, "Пользователь выбрал подробный ответ: раскрой выводы, evidence и ограничения."),
    "maximum": (16384, "Пользователь выбрал полный разбор: не сокращай полезные детали ради краткости."),
}


def apply_response_length(form: AnswerForm, preference: str | None) -> AnswerForm:
    """Apply an explicit operator preference to generation, not retrieval or routing.

    The operator-owned setting is allowed to change the token ceiling and add one
    lightweight instruction.  It does not choose facts, sources or professional
    decisions for the model.
    """
    selected = _RESPONSE_LENGTHS.get(str(preference or "").strip().casefold())
    if not selected:
        return form
    max_tokens, instruction = selected
    return AnswerForm(form.intent, " ".join(x for x in (form.instruction, instruction) if x), max_tokens)


def classify_answer_form(question: str) -> AnswerForm:
    """Детерминированно сопоставить вопрос с формой ответа (ADR-12 §2). Без LLM."""
    q = (question or "").strip().lower().replace("ё", "е")
    if not q:
        return _DEFAULT
    # «ё»-нормализация словаря под уже нормализованный вопрос.
    def _has(tokens: tuple[str, ...]) -> bool:
        return any(tok.replace("ё", "е") in q for tok in tokens)

    if _has(_VALUE_TOKENS):
        return _VALUE
    if _has(_FULL_TOKENS):
        return _FULL
    if _has(_ENUM_TOKENS):
        return _ENUM
    if _has(_BRIEF_TOKENS):
        return _BRIEF
    return _DEFAULT


TRUNCATION_NOTE = "\n\n_Ответ усечён по лимиту длины. Уточните вопрос или запросите подробный формат._"


def finalize_truncated_answer(text: str) -> str:
    """Mark the provider's length limit without deleting model-authored text.

    A dot may belong to a quantity, norm, table or source reference. Code must
    not invent a sentence boundary or silently discard the last decision.
    Structured model results are handled separately by the caller.
    """
    body = (text or "").rstrip()
    if not body:
        return body
    if body.lstrip().startswith(("{", "[", "```")):
        # Keep machine-readable model results intact, including incomplete JSON.
        # The caller records the length limit separately in retrieval_trace.
        return text
    return body + TRUNCATION_NOTE


_ECHO_MIN_RUN_CHARS = 200


def answer_echoes_prompt(answer: str, system_prompt: str) -> bool:
    """True, когда ответ пересказывает собственную инструкцию, а не отвечает.

    Малые модели при 2-битном квантовании иногда вырождаются и дословно повторяют
    системный промпт (наблюдалось на Carnice IQ2_M: ответ начинался с «Ты — Л.Е.С.»
    и зацикливался на блоке «# Правила»). Отдельные совпавшие формулировки — норма,
    поэтому эхом считается только длинный непрерывный кусок инструкции.
    """
    text = " ".join((answer or "").split())
    source = " ".join((system_prompt or "").split())
    if len(text) < _ECHO_MIN_RUN_CHARS or len(source) < _ECHO_MIN_RUN_CHARS:
        return False
    step = _ECHO_MIN_RUN_CHARS // 2
    for start in range(0, len(source) - _ECHO_MIN_RUN_CHARS + 1, step):
        if source[start:start + _ECHO_MIN_RUN_CHARS] in text:
            return True
    return False


_REPEAT_PROBE_CHARS = 160
_REPEAT_MAX_OCCURRENCES = 3


def answer_is_degenerate_repetition(answer: str) -> bool:
    """True, когда ответ зациклился на одном и том же фрагменте.

    Наблюдалось на Carnice IQ2_M: на новый вопрос модель повторила предыдущий ответ
    десятки раз подряд, пока не упёрлась в лимит. Отдельные совпадения (пункты списка,
    шапки разделов) короткие, поэтому проба берётся длинной — 160 символов подряд.
    """
    text = " ".join((answer or "").split())
    if len(text) < _REPEAT_PROBE_CHARS * _REPEAT_MAX_OCCURRENCES:
        return False
    probe = text[:_REPEAT_PROBE_CHARS]
    if text.count(probe) >= _REPEAT_MAX_OCCURRENCES:
        return True
    middle = text[len(text) // 2: len(text) // 2 + _REPEAT_PROBE_CHARS]
    return len(middle) == _REPEAT_PROBE_CHARS and text.count(middle) >= _REPEAT_MAX_OCCURRENCES


_CORPUS_STATE_BLOCKS = frozenset({
    "dataset_scope_not_found",
    "no_datasets",
    "corpus_empty",
})


def is_transient_retrieval_block(error_code: str) -> bool:
    """True для блокировок, вызванных неготовностью контура, а не состоянием корпуса.

    Сбой native RRF или реранкера проходит при повторе — это состояние сервиса, а не
    содержательный ответ. Сохранённая в историю заглушка попадает в контекст следующих
    запросов сессии, и модель начинает её копировать (наблюдалось: chat_history 185 → 186).
    Отсутствие датасета или пустой корпус, наоборот, ответ пользователю и в истории нужны.
    """
    code = str(error_code or "").strip()
    if not code:
        return False
    return code not in _CORPUS_STATE_BLOCKS


_MARKDOWN_LINK = re.compile(r"\[([^\]\n]{1,300})\]\(([^)\s]{1,2000})\)")


def strip_unsupported_links(answer: str, known_sources: Sequence[str]) -> tuple[str, int]:
    """Снять разметку ссылок, ведущих не на реальные источники ответа.

    Модель выдумывает адреса: в chat_history 193 источники были оформлены как
    `[Раздел ПД №8 ... .pdf](https://example.com/source1)`. Фальшивая ссылка в
    инженерном ответе хуже её отсутствия — по ней могут перейти. Текст ссылки
    сохраняем: он несёт имя документа и получен из выдачи.
    """
    text = answer or ""
    if "](" not in text:
        return text, 0
    haystack = "\n".join(str(item or "") for item in (known_sources or ()))
    removed = 0

    def replace(match: "re.Match[str]") -> str:
        nonlocal removed
        label, target = match.group(1), match.group(2)
        if target and target in haystack:
            return match.group(0)
        removed += 1
        return label

    return _MARKDOWN_LINK.sub(replace, text), removed
