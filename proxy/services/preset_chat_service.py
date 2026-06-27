"""preset_chat_service.py — переключение режима ЛЕС из чата: «режим локальный/облако/микс».

«какой режим?» → показать текущий; «режим облако» / «переключи на локальный» → применить.
0 LLM (regex). Канал `preset`.
"""
from __future__ import annotations

from typing import Any, Optional

from proxy.services.preset_service import (
    PRESETS,
    apply_preset,
    current_preset,
    describe,
    normalize_preset,
)


def is_preset_query(question: str) -> bool:
    q = (question or "").lower().replace("ё", "е").strip().lstrip("/")
    if q in ("режим", "режимы", "mode", "режим работы", "режим лес"):
        return True
    return bool("режим" in q and ("работ" in q or _mentions_preset(q) or "?" in q or "как" in q
                                  or "переключ" in q or "смени" in q or "какой" in q))


def _mentions_preset(q: str) -> Optional[str]:
    for token in list(PRESETS) + ["локал", "облак", "микс", "гибрид", "смешан", "офлайн", "local", "cloud", "mix"]:
        if token in q:
            return normalize_preset(token) or token
    return None


def _status_text() -> str:
    cur = current_preset()
    head = (f"Текущий режим: **{cur}** — {describe(cur)}." if cur
            else "Режим кастомный (настройки не совпадают с пресетом).")
    opts = "\n".join(f"  • {n} — {describe(n)}" for n in PRESETS)
    return f"{head}\nДоступно (скажи «режим <имя>»):\n{opts}"


def maybe_handle_preset_query(question: str, *, project_id: int = 0) -> Optional[dict[str, Any]]:
    if not is_preset_query(question):
        return None
    q = question.lower().replace("ё", "е")
    target = None
    for token in list(PRESETS) + list(("локал", "облак", "микс", "гибрид", "смешан", "офлайн")):
        if token in q:
            target = normalize_preset(token)
            if target:
                break
    if target is None:  # спросили про режим без указания — показать текущий + опции
        return {"answer": _status_text(), "operation": "preset_status"}
    try:
        res = apply_preset(target)
    except ValueError as err:
        return {"answer": str(err), "operation": "preset_error"}
    a = res["applied"]
    return {
        "answer": (f"Режим **{res['preset']}** — {describe(res['preset'])}.\n"
                   f"Чат: {a['LES_LLM_PROVIDER']} · скан-OCR: {a['RAG_OCR_BACKEND']} · "
                   f"приёмка ИД: {a['LES_ASBUILT_OCR_ENGINE']}. Применено сразу."),
        "operation": "preset_applied", "preset": res["preset"],
    }
