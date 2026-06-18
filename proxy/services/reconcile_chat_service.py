"""Сверка ВОР↔КС-2↔смета↔ИД как задача чата — W11.4b (LES3_PLAN).

«Сверка — не кнопка, а задача, которую система делает сама по запросу» (Олег).
Детерминированный (0 LLM) чат-канал: распознаёт намерение «сверь / сходятся ли
объёмы», сам находит проиндексированные табличные датасеты (Parquet), запускает
`reconcile_service` и формулирует ответ ГИП-стиля: сводка + топ расхождений/пробелов.
Числа считает Python над Parquet — как table_query/bor (ADR-11).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from proxy.services.reconcile_service import doc_type_label, reconcile_datasets

logger = logging.getLogger(__name__)

# Глаголы намерения сверки.
_RECONCILE_VERBS = (
    "свер",          # сверь / сверка / сверить
    "сходятся", "сходится", "сошлись",
    "совпада",       # совпадают / совпадает
    "соответств",    # соответствуют / соответствие
    "бьются", "бьется",
    "расхожд",       # расхождения / есть ли расхождения
    "сличи", "сличe",
)
# Контекст — о чём сверка (чтобы не ловить произвольное «соответствует»).
_RECONCILE_CONTEXT = (
    "вор", "кс-2", "кс2", "смет", "ведомост", "объем", "объём", "количеств",
    "позиц", "исполнительн", "ид ", "акт", "спецификац",
    "оборудован", "монтаж", "смонтир", "материал", "вложени", "докумен",
)


def is_reconcile_query(question: str) -> bool:
    """Намерение сверки: глагол сверки + контекст документов/объёмов. Без LLM."""
    q = f" {(question or '').lower().replace('ё', 'е')} "
    if not any(v.replace("ё", "е") in q for v in _RECONCILE_VERBS):
        return False
    return any(c.replace("ё", "е") in q for c in _RECONCILE_CONTEXT)


def find_parquet_dataset_ids(storage_root: Path) -> list[str]:
    """Все датасеты с табличными Parquet-строками (storage/datasets/<id>/_parquet/*.parquet)."""
    if not storage_root.exists():
        return []
    ids: list[str] = []
    for ds_dir in sorted(p for p in storage_root.iterdir() if p.is_dir()):
        parquet_dir = ds_dir / "_parquet"
        if parquet_dir.exists() and any(parquet_dir.rglob("*.parquet")):
            ids.append(ds_dir.name)
    return ids


def _format_answer(result: dict[str, Any]) -> str:
    doc_types = result["doc_types"]
    labels = result["doc_type_labels"]
    totals = result["totals"]
    rows = result["rows"]

    src_list = ", ".join(labels.get(dt, dt) for dt in doc_types)
    lines = [
        f"Сверка количеств по {totals['lines']} позициям. Источники: {src_list}.",
        f"✓ сходится: {totals['match']} · ⚠ расхождений: {totals['mismatch']} · "
        f"◌ пробелов: {totals['gap']} · один документ: {totals['single']}",
    ]

    if len(doc_types) < 2:
        only = labels.get(doc_types[0], doc_types[0]) if doc_types else "—"
        lines.append(
            f"\nПроиндексирован только один тип документа ({only}) — сравнивать не с чем. "
            "Для сверки нужны минимум два (например, смета и КС-2)."
        )
        return "\n".join(lines)

    mism = [r for r in rows if r["status"] == "mismatch"][:10]
    if mism:
        lines.append("\nРасхождения (число различается):")
        for r in mism:
            by = " vs ".join(
                f"{labels.get(dt, dt)} {r['qty_by_source'][dt]}"
                for dt in doc_types if r["qty_by_source"].get(dt) is not None
            )
            pct = f" — Δ {r['delta_pct']}%" if r["delta_pct"] is not None else ""
            lines.append(f"  • {r['name']} ({r['unit']}): {by}{pct}")

    gaps = [r for r in rows if r["status"] == "gap"][:10]
    if gaps:
        lines.append("\nПробелы (есть не во всех документах):")
        for r in gaps:
            present = ", ".join(labels.get(dt, dt) for dt in r["present"])
            missing = ", ".join(labels.get(dt, dt) for dt in r["missing"])
            lines.append(f"  • {r['name']} ({r['unit']}): есть в [{present}], нет в [{missing}]")

    if not mism and not gaps:
        lines.append("\nРасхождений и пробелов не найдено — объёмы сходятся.")

    lines.append("\nПолную таблицу выгрузить: Инструменты → Сверка → «Скачать xlsx» "
                 "(или POST /api/bor/reconcile/generate).")
    return "\n".join(lines)


def answer_reconcile_query(
    question: str,
    *,
    storage_root: Path = Path("./storage/datasets"),
    dataset_ids: list[str] | None = None,
    dataset_names: dict[str, str] | None = None,
    by: str = "dataset",
) -> dict[str, Any] | None:
    """Выполнить сверку по запросу чата. None — если данных нет вовсе. Без LLM.

    `dataset_ids` — явный scope (например, датасеты объекта); иначе берём все
    датасеты с Parquet. По умолчанию `by="dataset"` — сравниваем документы между
    собой (ведомость↔акт), а не схлопываем по типу.
    """
    ids = [d for d in (dataset_ids or []) if (storage_root / d / "_parquet").exists()]
    if not ids:
        ids = find_parquet_dataset_ids(storage_root)
    if not ids:
        return None

    # Ярлыки: переданные имена + имя файла вложения из _name.txt (скрепка чата).
    names = dict(dataset_names or {})
    for i in ids:
        if i not in names:
            name_file = storage_root / i / "_name.txt"
            if name_file.exists():
                try:
                    names[i] = name_file.read_text(encoding="utf-8").strip() or i
                except OSError:
                    pass

    result = reconcile_datasets(ids, storage_root=storage_root, by=by, dataset_names=names)
    if not result["rows"]:
        return None

    totals = result["totals"]
    return {
        "answer": _format_answer(result),
        "totals": totals,
        "doc_types": result["doc_types"],
        "dataset_ids": ids,
        "rows": result["rows"],
        "has_issues": bool(totals["mismatch"] or totals["gap"]),
    }
