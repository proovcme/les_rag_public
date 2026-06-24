"""project_registry_chat_service.py — «реестр проектов / общая карта папок» из чата.

Детерминированно (0 LLM): список всех объектов ЛЕС + папки + мета из LES.md. Канал `registry`.
"""
from __future__ import annotations

from typing import Any, Optional

# v0.17 баг-фикс: «реестр ДОКУМЕНТАЦИИ котельной» ≠ глобальный реестр проектов. Слова-сигналы
# документов внутри объекта: глобальный список НЕ должен срабатывать, даже если есть слово «реестр».
_DOC_SIGNAL = ("документ", "докум", "состав проектн", "не мусорн", "мусорн")


def is_registry_query(question: str) -> bool:
    """Интент ГЛОБАЛЬНЫЙ «реестр/карта ПРОЕКТОВ» — устойчиво к склонениям (по стемам).
    v0.17: запрос о ДОКУМЕНТАЦИИ/документах объекта сюда НЕ относится (scoped, см.
    is_document_registry_query) — иначе «реестр документации котельной» уходил в глобальный список."""
    q = (question or "").lower().replace("ё", "е")
    if any(s in q for s in _DOC_SIGNAL):                  # документация/документы → НЕ глобальный реестр
        return False
    if "реестр" in q or "что в работе" in q:
        return True
    if "карт" in q and "пап" in q:                        # «общую карту папок/папки»
        return True
    has_subj = "объект" in q or "проект" in q
    return has_subj and any(w in q for w in ("каки", "спис", "все ", "карт", "перечень"))


def is_document_registry_query(question: str) -> bool:
    """Интент SCOPED «реестр/состав документации проекта» — документы ВНУТРИ выбранного объекта."""
    q = (question or "").lower().replace("ё", "е")
    if "состав проектн" in q:
        return True
    if any(s in q for s in ("документ", "докум")) and any(
            w in q for w in ("реестр", "состав", "перечень", "выведи", "список", "покажи",
                             "дай ", "собери", "не мусорн", "каки", "что есть", "по проект")):
        return True
    return False


def maybe_handle_document_registry(question: str, *, project_id: int = 0,
                                   dataset_filter: str = "") -> Optional[dict[str, Any]]:
    """Scoped реестр документации. Есть scope (проект/датасет) → None (отвечает RAG по выбранному
    датасету, НЕ глобальный список). Нет scope → actionable MISSING (выберите проект/датасет)."""
    if not is_document_registry_query(question):
        return None
    has_scope = (isinstance(project_id, int) and project_id > 0) or bool((dataset_filter or "").strip())
    if has_scope:
        return None      # scope есть → RAG-конвейер ответит по документам выбранного объекта
    return {"answer": "Для реестра документации нужен выбранный проект или датасет. Выберите объект "
                      "в списке слева (или укажите датасет) — и соберу состав документов по нему.",
            "operation": "document_registry_no_scope", "missing": ["project_id|dataset_ids"]}


def registry_answer() -> dict[str, Any]:
    from proxy.services.project_service import build_registry

    reg = build_registry()
    if not reg["projects"]:
        return {"answer": "Объектов пока нет. «Пойми папку «<путь>»» — и появится первый "
                          "(или дай папку на индексацию — LES.md соберётся сам).",
                "operation": "registry_empty"}
    lines = [f"Реестр проектов ЛЕС — {reg['count']}:"]
    for p in reg["projects"][:40]:
        bits = [str(p["name"])]
        if p.get("stage"):
            bits.append(str(p["stage"]))
        if p.get("code"):
            bits.append(str(p["code"]))
        if p.get("address"):
            bits.append(str(p["address"]))
        tail = f"папок {len(p.get('folders') or [])}, датасетов {p.get('datasets', 0)}"
        flag = " ✓LES.md" if p.get("has_les_md") else ""
        lines.append(f"  • #{p['id']} {' · '.join(bits)} — {tail}{flag}")
    return {"answer": "\n".join(lines), "operation": "registry", "registry": reg}


def maybe_handle_registry_query(question: str, *, project_id: int = 0) -> Optional[dict[str, Any]]:
    if not is_registry_query(question):
        return None
    return registry_answer()
