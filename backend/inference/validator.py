"""Детерминированный rules-валидатор (ADR-11) — общий код для mlx_host и proxy.

Раньше жил только в `mlx_host._validate_with_rules`. Вынесен сюда, чтобы каскад
rules→LLM (W3.4) работал и в proxy для облачных провайдеров, у которых нет
своего `/api/validate`. Числа и лексику считает алгоритм, не LLM.

Статусы: VERIFIED / HALLUCINATION / NO_DATA.
"""

from __future__ import annotations

import os
import re

_STOPWORDS_RU = {
    "что", "это", "как", "так", "при", "для", "или", "над", "под",
    "если", "есть", "нужно", "нужен", "должна", "должен", "должно",
    "должны", "может", "могут", "более", "менее", "также", "либо",
    "иные", "иной", "иная", "такой", "такая", "такие", "через",
    "между", "после", "перед", "очень", "весь", "вся", "всех",
    "всем", "одного", "одной", "одним", "любом", "любой", "любых",
}


def normalize_rule_text(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", text.lower(), flags=re.UNICODE).split())


def extract_rule_numbers(text: str) -> set[str]:
    """Содержательные числа ответа/контекста (даты, годы, номера пунктов отброшены)."""
    cleaned = text.lower()
    cleaned = re.sub(r"\b\d{1,2}[.,/]\d{1,2}[.,/]\d{2,4}\b", "", cleaned)  # даты
    cleaned = re.sub(r"\b(?:19|20)\d{2}\b", "", cleaned)  # годы
    lines = []
    for line in cleaned.split("\n"):
        line = re.sub(r"^\s*\d+[\s.)-]", "", line)  # номера списков
        lines.append(line)
    cleaned = " ".join(lines)
    prefix_pat = (
        r"(?:раздел|п\.|пункт[ы]?|постановлени[ея]|№|от|n|рис|рисунок|таблиц[аы]|табл\.|стр\.)"
        r"\s*\d+(?:[-–—]\d+)?"
    )
    cleaned = re.sub(prefix_pat, "", cleaned)
    found: set[str] = set()
    for match in re.finditer(r"\b\d+(?:[,.]\d+)?\b", cleaned):
        num_str = match.group(0).replace(",", ".")
        end_idx = match.end()
        if "." in num_str:
            found.add(num_str)
            continue
        suffix = cleaned[end_idx : end_idx + 8].strip()
        if re.match(
            r"^(?:м\b|мм\b|см\b|мин\b|ч\b|сек\b|кг\b|°|ei|re|r\b|еи\b|квт\b|вт\b|чел\b|г\b|литр|куб)",
            suffix,
        ):
            found.add(num_str)
            continue
        try:
            if float(num_str) >= 100:
                found.add(num_str)
        except ValueError:
            pass
    return found


def lexical_overlap(answer: str, context: str, min_token_len: int = 4) -> float:
    """Доля значимых токенов ответа, найденных в контексте (0.0–1.0)."""
    norm_ctx = normalize_rule_text(context)
    tokens = re.findall(r"[а-яёa-z0-9]{%d,}" % min_token_len, answer.lower())
    meaningful = [t for t in tokens if t not in _STOPWORDS_RU]
    if not meaningful:
        return 0.0
    hits = sum(1 for t in meaningful if t in norm_ctx)
    return hits / len(meaningful)


def rules_validate(question: str, answer: str, context: str) -> dict:
    """Полный детерминированный вердикт (как старый `_validate_with_rules`).

    1. Пустой контекст → NO_DATA.
    2. Ответ дословно в контексте → VERIFIED.
    3. Числа ответа нарушают контекст → HALLUCINATION.
    4. Лексическое перекрытие ≥ порога → VERIFIED.
    5. Иначе → NO_DATA.
    """
    threshold = float(os.getenv("RULES_LEX_THRESHOLD", "0.35"))
    context = context or ""
    answer = answer or ""

    if not context.strip():
        return {"status": "NO_DATA", "raw": "empty_context", "backend": "rules", "unloaded_peer": []}

    if answer.strip() and normalize_rule_text(answer) in normalize_rule_text(context):
        return {"status": "VERIFIED", "raw": "answer_text_found_in_context", "backend": "rules", "unloaded_peer": []}

    answer_numbers = extract_rule_numbers(answer)
    context_numbers = extract_rule_numbers(context)
    if answer_numbers and context_numbers and not answer_numbers.issubset(context_numbers):
        return {
            "status": "HALLUCINATION",
            "raw": "answer_numeric_claim_not_in_context",
            "backend": "rules",
            "unloaded_peer": [],
        }

    overlap = lexical_overlap(answer, context)
    if overlap >= threshold:
        return {
            "status": "VERIFIED",
            "raw": f"lexical_overlap_{overlap:.2f}",
            "backend": "rules",
            "unloaded_peer": [],
            "lexical_overlap": overlap,
        }
    return {
        "status": "NO_DATA",
        "raw": f"rules_cannot_verify_overlap_{overlap:.2f}",
        "backend": "rules",
        "unloaded_peer": [],
        "lexical_overlap": overlap,
    }


def rules_pre_verdict(question: str, answer: str, context: str) -> str | None:
    """Каскад rules→LLM (W3.4): дешёвый детерминированный отсев ДО LLM-валидатора.

    Возвращает уверенный вердикт, который LLM не нужен:
      - NO_DATA  — пустой контекст (LLM сказал бы то же, экономим вызов);
      - HALLUCINATION — числовое утверждение ответа отсутствует в контексте
        (детерминированный числовой guard — облако его иначе могло пропустить).
    Возвращает None — неоднозначно, эскалируем к LLM-валидатору. ПОЛОЖИТЕЛЬНЫЙ
    вердикт (VERIFIED) намеренно НЕ выдаётся: подтверждение — работа LLM.
    """
    verdict = rules_validate(question, answer, context)
    if verdict["status"] in ("NO_DATA", "HALLUCINATION") and verdict["raw"] in (
        "empty_context",
        "answer_numeric_claim_not_in_context",
    ):
        return verdict["status"]
    return None
