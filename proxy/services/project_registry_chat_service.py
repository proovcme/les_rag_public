"""project_registry_chat_service.py — «реестр проектов / общая карта папок» из чата.

Детерминированно (0 LLM): список всех объектов ЛЕС + папки + мета из LES.md. Канал `registry`.
"""
from __future__ import annotations

from typing import Any, Optional

def is_registry_query(question: str) -> bool:
    """Интент «реестр/карта проектов» — устойчиво к склонениям и словам между (по стемам)."""
    q = (question or "").lower().replace("ё", "е")
    if "реестр" in q or "что в работе" in q:
        return True
    if "карт" in q and "пап" in q:                        # «общую карту папок/папки»
        return True
    has_subj = "объект" in q or "проект" in q
    return has_subj and any(w in q for w in ("каки", "спис", "все ", "карт", "перечень"))


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
