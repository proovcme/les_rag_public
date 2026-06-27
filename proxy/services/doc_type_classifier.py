"""doc_type_classifier — детерминированная классификация документа/дисциплины по ИМЕНИ файла (без LLM).

Вынесено из unified_construction_harness_service (v0.17), чтобы sidecar-операции и runtime-эндпоинты
не тянули весь unified-харнесс (flag-OFF, не деплоится). Лёгкий, без тяжёлых зависимостей.
"""

from __future__ import annotations


def classify_doc_type(name: str) -> str:
    """Имя файла/таблицы → doc_type. Без LLM. Акты смонтированного оборудования — отдельный тип."""
    n = (name or "").lower()
    if "акт" in n and any(k in n for k in ("смонтирован", "оборудован")):
        return "installed_equipment_act"
    if "ведомость смонтирован" in n or ("смонтированного оборудования" in n):
        return "installed_equipment_act"
    if "кс-2" in n or "кс2" in n:
        return "ks2"
    if "журнал работ" in n:
        return "work_log"
    if "исполнительн" in n or n.endswith("_ид.pdf") or "as-built" in n or "as_built" in n:
        return "asbuilt"
    if "спецификац" in n:
        return "specification"
    if "ф9" in n or "f9" in n or "ведомость объ" in n or n.startswith("вор") or "_вор" in n:
        return "f9_bor"
    if "лср" in n:
        return "lsr"
    if "смет" in n:
        return "estimate"
    if n.endswith(".dwg"):
        return "drawing"
    if any(k in n for k in ("свод правил", " сп ", "гост", "снип")):
        return "norm"
    if n.endswith(".eml") or "письм" in n or "переписк" in n:
        return "mail"
    if n.endswith(".parquet"):
        return "table"
    # справочные/внешние .md (Revit API / CAD-BIM экспорт) — не проектные документы
    if any(k in n for k in ("revit-api", "revit_api", "cad_bim", "cad-bim", "speckle", "_shard_", "fop20")):
        return "external_reference"
    if n.endswith((".pdf", ".docx", ".doc", ".md", ".txt")):
        return "project_doc"
    return "unknown"


_DISCIPLINE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("TM", ("тепломех", "_тм", "тм_", "тепломеханик")), ("GAS", ("газоснаб", "гсв")),
    ("AUPT", ("аупт", "пожаротуш")), ("APS", ("апс", "пожарн", "ппа")), ("DU", ("дымоудал",)),
    ("OV", ("отоплен", "вентиляц", "_ов")), ("VK", ("водоснаб", "канализац", "_вк")),
    ("EOM", ("электроснаб", "эом")), ("ARCH", ("архитект", "_ар")), ("KR", ("конструкц", "_кр")),
    ("estimate", ("смет", "лср")), ("asbuilt", ("исполнительн", "смонтирован")),
]


def classify_discipline(name: str) -> str:
    n = (name or "").lower()
    for disc, kw in _DISCIPLINE_RULES:
        if any(k in n for k in kw):
            return disc
    return "unknown"
