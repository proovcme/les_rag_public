"""Чат-канал «собери КС-2 / КС-3 / КС-6а» — детерминированно, 0 LLM.

Распознаёт намерение, собирает заполненный бланк через ks_forms_service и
возвращает ответ + download для GUI (как /-команды форм).
"""

from __future__ import annotations

import re
from typing import Any

from proxy.services import ks_forms_service

_BUILD_VERBS = (
    "собери", "соберить", "сформируй", "сформировать", "сделай", "выдай",
    "подготовь", "заполни", "выгрузи", "собери ",
)
_FORM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ks2", re.compile(r"\bкс[-\s]?2\b|кс2|акт[ае]?\s+выполнен", re.IGNORECASE)),
    ("ks3", re.compile(r"\bкс[-\s]?3\b|кс3|справк\w*\s+о\s+стоимост", re.IGNORECASE)),
    ("ks6a", re.compile(
        r"\bкс[-\s]?6\s*[аa]\b|кс6[аa]|журнал\w*\s+уч[её]т\w*\s+выполнен",
        re.IGNORECASE,
    )),
)


def detect_ks_form(question: str) -> str | None:
    """Return ks2|ks3|ks6a when the question asks to build that form."""
    q = (question or "").strip()
    if not q:
        return None
    q_l = q.casefold().replace("ё", "е")
    has_verb = any(v.replace("ё", "е") in q_l for v in _BUILD_VERBS)
    # Also accept bare «кс-2» / «кс-6а» as intent when clearly a form request.
    bare = bool(re.fullmatch(r"\s*/?\s*кс[-\s]?([23]|6\s*[аa])\s*", q_l))
    if not has_verb and not bare:
        return None
    for form_id, pattern in _FORM_PATTERNS:
        if pattern.search(q):
            return form_id
    return None


def is_ks_forms_query(question: str) -> bool:
    return detect_ks_form(question) is not None


def answer_ks_forms_query(
    question: str,
    *,
    project_id: int | None = None,
    session_id: str = "",
    fmt: str = "xlsx",
    assembled: dict[str, Any] | None = None,
    rim_form: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build filled KS document or return clarify payload (no silent blank success)."""
    form_id = detect_ks_form(question)
    if form_id is None:
        return {"ok": False, "clarify": True, "answer": "Укажите форму: КС-2, КС-3 или КС-6а."}

    titles = {
        "ks2": "Акт о приёмке выполненных работ (КС-2)",
        "ks3": "Справка о стоимости выполненных работ и затрат (КС-3)",
        "ks6a": "Журнал учёта выполненных работ (КС-6а)",
    }
    try:
        result = ks_forms_service.build_ks_document(
            form_id,
            fmt=fmt,
            project_id=project_id,
            session_id=session_id,
            assembled=assembled,
            rim_form=rim_form,
        )
    except ValueError as exc:
        return {
            "ok": False,
            "clarify": True,
            "form_id": form_id,
            "answer": str(exc),
            "command": {
                "action": "ks_forms_clarify",
                "form_id": form_id,
            },
        }

    path = result.get("path") or ""
    from pathlib import Path

    filename = Path(path).name if path else f"{form_id}.{fmt}"
    # Always keep a real extension — UI used to register the human title without
    # ".xlsx", and the browser/OS saved the ZIP/XLSX bytes as ".txt".
    if path and not filename.lower().endswith(f".{fmt}"):
        filename = f"{Path(filename).stem}.{fmt}"
    download = f"/api/forms/{form_id}/download?path={Path(path).name}" if path else ""

    if form_id == "ks6a":
        detail = f"записей журнала: {result.get('entries', 0)}"
        note = "Источник: confirmed журнал полевых объёмов."
    else:
        detail = (
            f"позиций ЛСР: {result.get('positions', 0)}, "
            f"сумма: {result.get('total', 0):.2f} ₽"
        )
        note = (
            "Строки перенесены из последней ЛСР за отчётный период "
            "(не независимый факт ИД)."
        )
        if result.get("draft"):
            note += (
                " Это явно маркированный черновик из ЛСР: он не подтверждает "
                "фактическое выполнение и не является подписным КС."
            )

    answer = (
        f"**{titles[form_id]}** сформирован ({detail}).\n"
        f"{note}\n"
        "Файл — в панели «Файлы» / по download."
    )
    return {
        "ok": True,
        "form_id": form_id,
        "answer": answer,
        "path": path,
        "download": download,
        "filename": filename,
        "filled": True,
        "source": result.get("source"),
        "document_status": result.get("document_status"),
        "draft": bool(result.get("draft")),
        "command": {
            "action": "generate_filled_form",
            "form_id": form_id,
            "fmt": fmt,
            "title": titles[form_id],
            "filename": filename,
            "download": download,
            "path": path,
            "source": result.get("source"),
            "document_status": result.get("document_status"),
            "draft": bool(result.get("draft")),
        },
        "totals": {
            "positions": result.get("positions"),
            "entries": result.get("entries"),
            "total": result.get("total"),
        },
    }
