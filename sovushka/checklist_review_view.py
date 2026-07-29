"""С.О.В.У.Ш.К.А. — чистые UI-хелперы для «Проверка по чек-листу» (T5.1, Phase 5).

Паттерн — по образцу ``sovushka/m5_display.py``: модуль без NiceGUI-импортов, принимает/отдаёт
только dict/list (форма ``checklist_review_v1`` из ``proxy/services/checklist_review_service.py``,
та же, что читает ``proxy/routers/checklist_review.py``). Тестируется прямым вызовом функций
(``tests/test_checklist_review_view.py``) — без запуска NiceGUI/HTTP. NiceGUI-обвязка
(``sovushka/pages/instrumenty.py``) вызывает эти функции и только рендерит их результат.

Русские ярлыки ``suggested_answer``/``status`` намеренно ДУБЛИРУЮТ словари
``proxy/services/checklist_report_service.py`` (``_ANSWER_LABELS_RU``) — UI, XLSX и HTML должны
говорить одним языком на одних и тех же данных (см. тест
``test_format_item_row_suggested_answer_labels_match_report_service``). Дублирование, а не импорт
приватных имён другого слоя (proxy vs sovushka — разные процессы/деплой-юниты в этом репо, тянуть
приватный символ через границу пакетов — плохая идея), сверка тестом.
"""

from __future__ import annotations

from typing import Any

_MAX_CRITERION_LEN = 120

# Дубликат proxy/services/checklist_report_service._ANSWER_LABELS_RU (см. docstring модуля).
_ANSWER_LABELS_RU: dict[str, str] = {
    "yes": "Да",
    "no": "Нет",
    "not_required": "Не требуется",
    "unknown": "—",
    "manual_required": "Требует инженера",
}

_HUMAN_ANSWER_LABELS_RU: dict[str, str] = {
    "yes": "Да",
    "no": "Нет",
    "not_required": "Не требуется",
}

_STATUS_LABELS_RU: dict[str, str] = {
    "supported_by_evidence": "Есть подтверждение",
    "computed_issue": "Формальная проблема",
    "review_needed": "Нужно проверить",
    "manual_required": "Решение инженера",
    "not_applicable": "Не относится",
}


def _answer_label(value: str) -> str:
    return _ANSWER_LABELS_RU.get(value, value or "—")


def _truncate(text: str, limit: int = _MAX_CRITERION_LEN) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _evidence_refs(item: dict[str, Any]) -> list[dict[str, Any]]:
    """document_evidence-записи с непустым source_ref (единственный признак «есть evidence»,
    зеркалит ``checklist_review_service._summarize``/``checklist_report_service._evidence_text``)."""
    out = []
    for ev in (item or {}).get("document_evidence") or []:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("source_ref") or "").strip():
            out.append(ev)
    return out


# ── format_item_row ──────────────────────────────────────────────────────────────────────────


def format_item_row(item: dict[str, Any]) -> dict[str, Any]:
    """Строка таблицы items для NiceGUI ``ui.table``: № / критерий (обрезанный + полный для
    drawer) / suggested русским ярлыком / уверенность / evidence count / human answer.

    Пустой/неполный ``item`` не роняет функцию (T5.1 п.1 «тесты на пустые поля») — все поля
    получают безопасные дефолты.
    """
    item = item or {}
    criterion_full = str(item.get("criterion") or "")
    human_answer = str(item.get("human_answer") or "unset")

    return {
        "item_id": str(item.get("item_id") or ""),
        "item_no": str(item.get("item_no") or ""),
        "discipline": str(item.get("discipline") or ""),
        "criterion_full": criterion_full,
        "criterion_short": _truncate(criterion_full),
        "status": str(item.get("status") or ""),
        "status_label": _STATUS_LABELS_RU.get(
            str(item.get("status") or ""),
            str(item.get("status") or "—"),
        ),
        "suggested_answer": str(item.get("suggested_answer") or ""),
        "suggested_label": _answer_label(str(item.get("suggested_answer") or "")),
        "confidence": item.get("confidence", ""),
        "evidence_count": len(_evidence_refs(item)),
        "model_note": str(item.get("model_note") or ""),
        "human_answer": human_answer,
        "human_answer_label": _HUMAN_ANSWER_LABELS_RU.get(human_answer, ""),
        "human_note": str(item.get("human_note") or item.get("human_comment") or ""),
    }


# ── summary_chips ────────────────────────────────────────────────────────────────────────────

# Порядок и подписи чипов сводки — CHECKLIST_REVIEW_PD_TASK.md §7
# «summary: всего / yes / no / manual_required / unknown / confirmed» + human-блок из роутера
# (``_apply_decisions`` -> ``summary.human``). "confirmed" в §7 разворачиваем как отдельный чип
# «Подтверждено человеком» = сумма human.yes+no+not_required (без unset) — единое число,
# сколько пунктов инженер уже закрыл, вне зависимости от того, каким было решение.
_CHIP_SPECS: tuple[tuple[str, str], ...] = (
    ("total", "Всего"),
    ("yes", "Да"),
    ("no", "Нет"),
    ("not_required", "Не требуется"),
    ("manual_required", "Требует инженера"),
    ("unknown", "Неизвестно"),
    ("human_confirmed", "Подтверждено человеком"),
)


def summary_chips(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Чипы сводки прогона: всего/да/нет/не требуется/требует инженера/неизвестно/подтверждено
    человеком. Пустой ``summary`` -> все значения 0 (не рушится на прогоне без items/decisions)."""
    summary = summary or {}
    suggested = summary.get("suggested") or {}
    human = summary.get("human") or {}

    values: dict[str, Any] = {
        "total": summary.get("total", 0) or 0,
        "yes": suggested.get("yes", 0) or 0,
        "no": suggested.get("no", 0) or 0,
        "not_required": suggested.get("not_required", 0) or 0,
        "manual_required": suggested.get("manual_required", 0) or 0,
        "unknown": suggested.get("unknown", 0) or 0,
        "human_confirmed": (
            (human.get("yes", 0) or 0)
            + (human.get("no", 0) or 0)
            + (human.get("not_required", 0) or 0)
        ),
    }

    return [{"key": key, "label": label, "value": values[key]} for key, label in _CHIP_SPECS]


def evidence_lines(item: dict[str, Any]) -> list[str]:
    """Строки «source_ref — snippet» для drawer (по образцу
    ``checklist_report_service._evidence_text``, но текстовые строки, а не одна ячейка XLSX).
    Записи без source_ref пропускаются (не считаются evidence — правило T2.x «suggested без
    evidence не даёт yes/no»), None-элементы списка игнорируются."""
    lines = []
    for ev in _evidence_refs(item):
        ref = str(ev.get("source_ref") or "").strip()
        snippet = str(ev.get("snippet") or "").strip()
        lines.append(f"{ref} — {snippet}" if snippet else ref)
    return lines
