"""project_registry_chat_service.py — typed project-registry tool.

Код возвращает модели список объектов и метаданные, но не готовый visible answer.
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
                                   dataset_filter: str = "",
                                   dataset_ids: Optional[list] = None) -> Optional[dict[str, Any]]:
    """Scoped реестр документации. Есть scope → None (отвечает RAG по выбранному объекту, НЕ
    глобальный список). Нет scope → actionable MISSING (выберите проект/датасет).

    Scope = ЕДИНЫЙ: project_id | dataset_filter (legacy) | dataset_ids (ScopeSelector/resolve_scope).
    Раньше канал был слеп к dataset_ids → при выбранном через ScopeSelector датасете (приходит
    dataset_ids, а не dataset_filter) ложно отбивал «выберите объект». Теперь видит все формы scope."""
    if not is_document_registry_query(question):
        return None
    has_scope = ((isinstance(project_id, int) and project_id > 0)
                 or bool((dataset_filter or "").strip())
                 or bool(dataset_ids))
    if has_scope:
        return None      # scope есть → RAG-конвейер ответит по документам выбранного объекта
    return {
        "operation": "document_registry_no_scope",
        "status": "blocked",
        "error_code": "MISSING_SCOPE",
        "missing": ["project_id|dataset_ids"],
    }


def registry_tool_result() -> dict[str, Any]:
    from proxy.services.project_service import build_registry

    reg = build_registry()
    return {
        "operation": "project_registry_lookup",
        "status": "ok" if reg["projects"] else "empty",
        "registry": reg,
    }


def maybe_handle_registry_query(question: str, *, project_id: int = 0) -> Optional[dict[str, Any]]:
    """Legacy visible-answer entrypoint is disabled: professional final belongs to the model."""
    return None
