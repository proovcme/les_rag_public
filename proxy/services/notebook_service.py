"""Unified LES notebook layer.

Notebook is navigation/context, not evidence. It sits on top of dataset
profiles and service-source catalogs so every workflow can receive the same
compact map of what is available and how to search it.
"""

from __future__ import annotations

import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from proxy.services.context_memory_service import (
    build_dataset_profile,
    warmup_dataset_profiles,
)

NOTEBOOK_SCHEMA = "notebook_v1"
NOTEBOOK_CONTEXT_SCHEMA = "notebook_context_v1"

_WORD_RE = re.compile(r"[а-яёa-z0-9]{4,}", re.I)
_COLLECTION_RE = re.compile(r"(?<!\d)(\d{2})-\d{2}-\d{3}-\d{2}")
_STOPWORDS = frozenset(
    "работ устройство устройств монтаж демонтаж конструкций конструкция при для или над под без "
    "выполнение изготовление установка прокладка разных группе групп".split()
)

_GESN_COLLECTION_LABELS = {
    "01": "земляные работы",
    "05": "свайные работы, фундаменты и основания",
    "06": "бетонные и железобетонные монолитные конструкции",
    "07": "бетонные и железобетонные сборные конструкции",
    "08": "конструкции из кирпича и блоков",
    "09": "металлические конструкции",
    "ГЭСНм38": "монтаж металлических и листовых конструкций, оборудования и тяжёлых узлов",
    "10": "деревянные конструкции",
    "11": "полы",
    "12": "кровли",
    "15": "отделочные работы",
    "16": "трубопроводы внутренние",
    "17": "водопровод и канализация",
    "18": "отопление",
    "20": "вентиляция и кондиционирование",
    "21": "электромонтажные работы",
    "22": "сети связи и слаботочные системы",
}


def _top(values: list[str], *, limit: int = 10) -> list[str]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip().lower()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return [key for key, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _keywords(texts: list[str], *, limit: int = 12) -> list[str]:
    counts: dict[str, int] = {}
    for text in texts:
        for word in _WORD_RE.findall(str(text or "").lower()):
            if word in _STOPWORDS or len(word) < 4:
                continue
            stem = word[:14]
            counts[stem] = counts.get(stem, 0) + 1
    return [word for word, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _dataset_notebook_summary(profile: dict[str, Any]) -> dict[str, Any]:
    deep = profile.get("deep") if isinstance(profile.get("deep"), dict) else {}
    doc_types = [str(x.get("value")) for x in profile.get("document_types", []) if x.get("value")]
    domains = [str(x.get("value")) for x in profile.get("domains", []) if x.get("value")]
    routes = [str(x.get("value")) for x in profile.get("routes", []) if x.get("value")]
    terms = list(deep.get("content_keywords") or profile.get("keywords") or [])[:16]
    norm_refs = list(deep.get("norm_refs") or [])[:12]
    table_signal = int(deep.get("table_signal_chunks") or 0)
    limitations = [
        "Блокнот описывает индекс и навигацию; утверждения в ответе должны ссылаться на найденные источники.",
    ]
    if not deep.get("available"):
        limitations.append("Deep-паспорт недоступен или пуст; доступна только metadata-карта.")
    if table_signal:
        limitations.append("В датасете есть табличные признаки; для сумм/количеств нужен табличный инструмент.")
    return {
        "purpose": "навигация по датасету и выбор правильного workflow",
        "document_types": doc_types[:8],
        "subject_areas": [x for x in [*domains, *routes] if x][:10],
        "key_terms": terms,
        "norm_refs": norm_refs,
        "limitations": limitations,
        "search_hints": [
            "используй как фон для выбора источников и инструмента",
            "не считай этот блокнот evidence",
            "для чисел ищи исходные строки/таблицы и считай кодом",
        ],
    }


def _dataset_prompt_excerpt(notebook: dict[str, Any]) -> str:
    summary = notebook.get("notebook_summary") or {}
    bits = [
        f"Блокнот датасета {notebook.get('name') or notebook.get('dataset_id')}: "
        f"{notebook.get('document_count', 0)} файлов, {notebook.get('chunk_count', 0)} чанков.",
    ]
    if summary.get("subject_areas"):
        bits.append("Области: " + ", ".join(summary["subject_areas"][:8]) + ".")
    if summary.get("key_terms"):
        bits.append("Термины: " + ", ".join(summary["key_terms"][:10]) + ".")
    if summary.get("norm_refs"):
        bits.append("Частые нормы: " + ", ".join(summary["norm_refs"][:8]) + ".")
    bits.append("Это навигация, не evidence.")
    return "\n".join(bits)


def build_dataset_notebook(
    dataset_id: str,
    *,
    storage_root: Path = Path("storage/datasets"),
    depth: str = "deep",
    force: bool = False,
) -> dict[str, Any]:
    profile = build_dataset_profile(dataset_id, storage_root=storage_root, depth=depth, force=force)
    notebook = {
        "schema": NOTEBOOK_SCHEMA,
        "kind": "dataset_notebook",
        "dataset_id": profile.get("dataset_id", dataset_id),
        "name": profile.get("name", dataset_id),
        "depth": profile.get("depth", depth),
        "document_count": profile.get("document_count", 0),
        "chunk_count": profile.get("chunk_count", 0),
        "profile": profile,
        "notebook_summary": _dataset_notebook_summary(profile),
        "context_role": "navigation",
        "is_evidence": False,
        "updated_at": time.time(),
    }
    notebook["prompt_excerpt"] = _dataset_prompt_excerpt(notebook)
    return notebook


def warmup_dataset_notebooks(
    *,
    dataset_ids: list[str] | None = None,
    storage_root: Path = Path("storage/datasets"),
    depth: str = "deep",
    force: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    profiles = warmup_dataset_profiles(
        dataset_ids=dataset_ids,
        storage_root=storage_root,
        depth=depth,
        force=force,
        limit=limit,
    )
    notebooks = []
    for item in profiles.get("profiles") or []:
        dataset_id = str(item.get("dataset_id") or "")
        if not dataset_id:
            continue
        notebooks.append(build_dataset_notebook(dataset_id, storage_root=storage_root, depth=depth))
    return {
        "schema": NOTEBOOK_SCHEMA,
        "kind": "notebook_warmup",
        "status": profiles.get("status"),
        "requested": profiles.get("requested", 0),
        "built": len(notebooks),
        "errors": profiles.get("errors", []),
        "notebooks": [
            {
                "dataset_id": n.get("dataset_id"),
                "name": n.get("name"),
                "document_count": n.get("document_count"),
                "chunk_count": n.get("chunk_count"),
                "summary": n.get("notebook_summary"),
            }
            for n in notebooks
        ],
    }


def _collection_of(code: str) -> str:
    match = _COLLECTION_RE.search(str(code or ""))
    return match.group(1) if match else ""


def _base_type_of(code: str, norm: dict[str, Any] | None = None) -> str:
    base_type = str((norm or {}).get("base_type") or "").strip()
    if base_type:
        return base_type
    value = str(code or "").strip()
    if value.startswith("ГЭСНм"):
        return "ГЭСНм"
    if value.startswith("ГЭСНр"):
        return "ГЭСНр"
    if value.startswith("ГЭСНп"):
        return "ГЭСНп"
    return "ГЭСН"


def _collection_id(code: str, norm: dict[str, Any] | None = None) -> str:
    collection = _collection_of(code)
    if not collection:
        return ""
    base_type = _base_type_of(code, norm)
    return collection if base_type == "ГЭСН" else f"{base_type}{collection}"


@lru_cache(maxsize=1)
def build_gesn_notebook() -> dict[str, Any]:
    from proxy.services.gesn_service import load_base_norms, load_norms

    norms = {**load_base_norms(), **load_norms()}
    grouped: dict[str, dict[str, Any]] = {}
    for code, norm in norms.items():
        display_code = str(norm.get("code") or code)
        collection = _collection_id(display_code, norm)
        if not collection:
            continue
        rec = grouped.setdefault(collection, {"names": [], "units": [], "examples": []})
        name = str(norm.get("name") or "")
        rec["names"].append(name)
        rec["units"].append(str(norm.get("unit") or ""))
        if len(rec["examples"]) < 5:
            rec["examples"].append({"code": display_code, "name": name, "unit": norm.get("unit") or ""})

    collections: list[dict[str, Any]] = []
    for collection in sorted(set(_GESN_COLLECTION_LABELS) | set(grouped)):
        data = grouped.get(collection, {"names": [], "units": [], "examples": []})
        label = _GESN_COLLECTION_LABELS.get(collection, "сборник ГЭСН")
        collections.append(
            {
                "collection": collection,
                "area": label,
                "norms": len(data["names"]),
                "typical_terms": _keywords(data["names"], limit=10),
                "units": _top(data["units"], limit=6),
                "examples": data["examples"],
                "search_hints": [
                    f"используй сборник {collection} для работ области: {label}",
                    "проверяй единицу измерения нормы перед расчётом",
                    "не подменяй область работ соседним сборником без подтверждения применимости",
                ],
            }
        )

    notebook = {
        "schema": NOTEBOOK_SCHEMA,
        "kind": "service_source_notebook",
        "id": "gesn",
        "name": "ГЭСН: карта сборников",
        "context_role": "navigation",
        "is_evidence": False,
        "notebook_summary": {
            "purpose": "навигация по сборникам ГЭСН для выбора области поиска нормы",
            "limitations": [
                "Карта сборников не является нормой и не подтверждает применимость позиции.",
                "Коды, объёмы и деньги подтверждаются только инструментами search_norm/add_position.",
            ],
            "search_hints": [
                "сначала определи семейство работ, потом ищи норму внутри подходящего сборника",
                "если работа описана широко, верни кандидаты или запроси параметры",
                "числа не придумывать: расчёт делает код",
            ],
        },
        "collections": collections,
        "updated_at": time.time(),
    }
    notebook["prompt_excerpt"] = gesn_notebook_prompt_excerpt(notebook)
    return notebook


def gesn_notebook_prompt_excerpt(notebook: dict[str, Any] | None = None, *, collections: list[str] | None = None) -> str:
    nb = notebook or build_gesn_notebook()
    wanted = set(collections or ["01", "05", "06", "07", "08", "09", "ГЭСНм38", "10", "11", "12", "15", "16", "17", "18", "20", "21", "22"])
    rows = [
        c for c in nb.get("collections", [])
        if str(c.get("collection")) in wanted
    ]
    lines = ["[Блокнот ГЭСН: карта сборников, навигация НЕ evidence]"]
    for c in rows:
        terms = ", ".join(_keywords([str(c.get("area") or "")], limit=4))
        units = ", ".join((c.get("units") or [])[:4])
        lines.append(
            f"{c.get('collection')}: {c.get('area')} · термины: {terms or '—'} · ед.: {units or '—'}"
        )
    lines.append("Правило: модель выбирает область работ; нормы/объёмы/деньги подтверждают инструменты.")
    return "\n".join(lines)


def service_source_notebooks() -> dict[str, Any]:
    gesn = build_gesn_notebook()
    return {
        "schema": NOTEBOOK_SCHEMA,
        "kind": "service_source_notebooks",
        "notebooks": [
            {
                "id": "gesn",
                "name": gesn["name"],
                "context_role": gesn["context_role"],
                "is_evidence": gesn["is_evidence"],
                "notebook_summary": gesn["notebook_summary"],
                "collections": gesn["collections"],
                "prompt_excerpt": gesn["prompt_excerpt"],
            }
        ],
    }
