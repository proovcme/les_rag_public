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
from proxy.services.dataset_memory_service import (
    build_typed_dataset_memory,
    dataset_brief_for_model,
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
    "02": "горновскрышные работы",
    "03": "буровзрывные работы",
    "04": "скважины",
    "05": "свайные работы, фундаменты и основания",
    "06": "бетонные и железобетонные монолитные конструкции",
    "07": "бетонные и железобетонные сборные конструкции",
    "08": "конструкции из кирпича и блоков",
    "09": "металлические конструкции",
    "ГЭСНм38": "монтаж металлических и листовых конструкций, оборудования и тяжёлых узлов",
    "ГЭСНм10": "монтаж оборудования связи, СКС, ВОЛС и слаботочных систем",
    "10": "деревянные конструкции",
    "11": "полы",
    "12": "кровли",
    "13": "защита строительных конструкций и оборудования от коррозии",
    "14": "конструкции в сельском строительстве",
    "15": "отделочные работы",
    "16": "трубопроводы внутренние",
    "17": "водопровод и канализация",
    "18": "отопление",
    "19": "газоснабжение внутреннее",
    "20": "вентиляция и кондиционирование",
    "21": "электромонтажные работы",
    "22": "водопровод наружный",
    "23": "канализация наружная",
    "24": "теплоснабжение и газопроводы наружные",
    "34": "сооружения связи, радиовещания и телевидения",
    "46": "работы при реконструкции зданий и сооружений",
}

_SMETA_SOURCE_LAYERS: list[dict[str, Any]] = [
    {
        "id": "norms",
        "title": "Нормы ГЭСН/ГЭСНм/ГЭСНп/ГЭСНр",
        "role": "состав работ, измеритель нормы и ресурсы на единицу",
        "not_role": "не текущая цена и не финальный итог",
    },
    {
        "id": "resources",
        "title": "Ресурсы нормы",
        "role": "труд, машины, материалы, оборудование для дальнейшей оценки",
        "not_role": "не поставка пользователя и не замена ВОР",
    },
    {
        "id": "fgis_split",
        "title": "Сплит-формы / локальные книги ФГИС ЦС",
        "role": "цены и индексы по ресурсам для региона и периода",
        "not_role": "не выбирают работу и не подтверждают применимость нормы",
    },
    {
        "id": "nr_sp",
        "title": "НР/СП и методические документы",
        "role": "правила начислений после раскрытия ресурсов и ФОТ",
        "not_role": "не произвольный процент сверху",
    },
    {
        "id": "lsr_form",
        "title": "Форма ЛСР / Методика 421/пр",
        "role": "форма вывода, графы, разделы, итоги и trace",
        "not_role": "не источник состава работ",
    },
    {
        "id": "project_sources",
        "title": "Проектные ВОР, спецификации, ТЗ, история",
        "role": "состав работ, объёмы и договорные исключения",
        "not_role": "не нормативная база сама по себе",
    },
]

_SMETA_DOMAIN_ROUTES: list[dict[str, Any]] = [
    {
        "domain": "СКС / связь / ВОЛС / слаботочные системы",
        "keys": ["ГЭСНм10", "34"],
        "route": "сначала ВОР по шкафам, трассам, кабелю, оконцеванию, маркировке, измерениям; затем поиск норм связи/монтажа",
        "caution": "не заменять всю СКС одной строкой поставки кабеля; активное оборудование и ПНР отделять",
    },
    {
        "domain": "ЭОМ / силовые сети / освещение",
        "keys": ["21"],
        "route": "кабельные линии, короба/лотки, светильники, щиты, подключение и испытания вести построчно",
        "caution": "СКС и ЭОМ не смешивать в один сборник; проверять единицу м/100 м/шт",
    },
    {
        "domain": "ОВ / вентиляция / кондиционирование",
        "keys": ["18", "20"],
        "route": "воздуховоды, оборудование, арматура, изоляция, испытания и ПНР разделять по действиям",
        "caution": "монтаж оборудования и устройство сетей могут идти разными нормами",
    },
    {
        "domain": "ВК / НВК / трубопроводы",
        "keys": ["16", "17", "22", "23", "24"],
        "route": "внутренние и наружные сети разделять; трубы, фасонные части, арматуру, испытания вести раздельно",
        "caution": "материал трубы и диаметр часто являются условием применимости",
    },
    {
        "domain": "Металлоконструкции и тяжёлый монтаж",
        "keys": ["09", "ГЭСНм38"],
        "route": "изготовление/поставка отдельно, монтаж/сборка/болтовые соединения/такелаж отдельно",
        "caution": "давальческий металл 0 руб не обнуляет монтаж; масса может быть объёмом нескольких разных операций",
    },
    {
        "domain": "Отделка / покрытия / защита",
        "keys": ["13", "15", "46"],
        "route": "подготовка основания, нанесение, окраска, защитные покрытия и демонтаж разделяются",
        "caution": "слои, основание и материал покрытия влияют на норму",
    },
    {
        "domain": "Кровля / гидроизоляция",
        "keys": ["12"],
        "route": "пирог, основание, примыкания, утепление и покрытия вести отдельными строками",
        "caution": "площадь материала не всегда равна площади работы без нахлёстов/примыканий",
    },
    {
        "domain": "Земляные, основания, бетон",
        "keys": ["01", "05", "06", "07", "11"],
        "route": "грунт, основания, бетон/арматура/опалубка, сборные элементы и полы разделять",
        "caution": "группа грунта, глубина, крепления, класс бетона и геометрия часто блокируют priced_final",
    },
]


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
    top_documents = list(deep.get("top_documents") or profile.get("top_documents") or profile.get("sample_files") or [])
    priority_files = []
    for item in top_documents[:16]:
        name = str(item.get("doc_name") or item.get("file_name") or "")
        if not name:
            continue
        priority_files.append(
            {
                "file_name": name,
                "chunks": int(item.get("chunks") or item.get("chunk_count") or 0),
                "status": str(item.get("status") or ""),
                "role_hint": str(item.get("doc_type") or item.get("domain") or item.get("route_dataset") or ""),
                "source": str(item.get("source") or "lexical_chunks"),
            }
        )
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
        "priority_files": priority_files,
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
    if summary.get("priority_files"):
        names = [str(item.get("file_name") or "") for item in summary["priority_files"][:8]]
        bits.append("Открывать в первую очередь: " + "; ".join(name for name in names if name) + ".")
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
    typed_memory = build_typed_dataset_memory(dataset_id, force=force)
    summary = _dataset_notebook_summary(profile)
    notebook = {
        "schema": NOTEBOOK_SCHEMA,
        "kind": "dataset_notebook",
        "dataset_id": profile.get("dataset_id", dataset_id),
        "name": profile.get("name", dataset_id),
        "depth": profile.get("depth", depth),
        "document_count": profile.get("document_count", 0),
        "chunk_count": profile.get("chunk_count", 0),
        "profile": profile,
        "typed_memory": typed_memory,
        "notebook_summary": summary,
        "priority_files": summary.get("priority_files", []),
        "context_role": "navigation",
        "is_evidence": False,
        "updated_at": time.time(),
    }
    notebook["prompt_excerpt"] = _dataset_prompt_excerpt(notebook)
    return notebook


def dataset_memory_prompt_excerpt(dataset_ids: list[str], *, question: str = "") -> str:
    memories = []
    for dataset_id in dataset_ids:
        try:
            memories.append(build_typed_dataset_memory(str(dataset_id)))
        except Exception:
            continue
    return dataset_brief_for_model(memories, question=question)


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


@lru_cache(maxsize=1)
def build_smeta_norm_rag_notebook() -> dict[str, Any]:
    """Build a model-facing smeta RAG map.

    This notebook is navigation only. It exposes what the smeta corpus contains
    and how to move through it, but it does not choose a norm for any user row.
    """
    from proxy.services.smeta_norm_store import get_smeta_norm_store

    store = get_smeta_norm_store()
    payload = store.payload()
    by_collection: dict[str, dict[str, Any]] = {}
    for row in store.rows:
        rec = by_collection.setdefault(
            row.collection_key,
            {
                "collection": row.collection_key,
                "area": _GESN_COLLECTION_LABELS.get(row.collection_key, f"сборник {row.collection_key}"),
                "norms": 0,
                "units": [],
                "resource_kinds": [],
                "examples": [],
            },
        )
        rec["norms"] += 1
        rec["units"].append(row.measure_unit)
        rec["resource_kinds"].extend(str(row.resource_kinds or "").split(","))
        if len(rec["examples"]) < 3:
            card = row.profile().get("model_card") or {}
            rec["examples"].append(
                {
                    "code": row.code,
                    "name": row.title[:180],
                    "unit": row.measure_unit,
                    "resources": card.get("resources", {}),
                    "conditions_to_check": card.get("conditions_to_check", [])[:6],
                    "provenance": row.provenance,
                }
            )
    collections = []
    wanted = {key for route in _SMETA_DOMAIN_ROUTES for key in route["keys"]}
    wanted.update(["01", "05", "06", "09", "12", "15", "21", "ГЭСНм10", "ГЭСНм38"])
    for key in sorted(wanted):
        rec = by_collection.get(key)
        if not rec:
            collections.append(
                {
                    "collection": key,
                    "area": _GESN_COLLECTION_LABELS.get(key, f"сборник {key}"),
                    "norms": 0,
                    "units": [],
                    "resource_kinds": [],
                    "examples": [],
                    "status": "not_in_current_store",
                }
            )
            continue
        collections.append(
            {
                "collection": rec["collection"],
                "area": rec["area"],
                "norms": rec["norms"],
                "units": _top(rec["units"], limit=6),
                "resource_kinds": _top(rec["resource_kinds"], limit=6),
                "examples": rec["examples"],
                "status": "available",
            }
        )

    notebook = {
        "schema": NOTEBOOK_SCHEMA,
        "kind": "service_source_notebook",
        "id": "smeta_norms",
        "name": "Сметный RAG: нормы, ресурсы, цены и форма ЛСР",
        "context_role": "navigation",
        "is_evidence": False,
        "notebook_summary": {
            "purpose": "помочь модели идти по сметному датасету: ВОР → нормативный маршрут → полный шифр → ресурсы → цены → ЛСР",
            "limitations": [
                "Блокнот не выбирает норму за модель и не является evidence.",
                "Полный шифр нормы становится расчётным входом только после решения модели.",
                "Строки без полного шифра остаются scenario/partial/missing, а не priced_final.",
            ],
            "search_hints": [
                "сначала определи раздел работ и физический объём",
                "затем найди подходящую базу/сборник/таблицу и сравни соседние нормы",
                "после принятия нормы пиши полный шифр в графе Обоснование",
                "после полного шифра расчётный слой раскрывает ресурсы, ФГИС/индексы, НР/СП и ЛСР",
            ],
        },
        "norm_store": payload,
        "source_layers": _SMETA_SOURCE_LAYERS,
        "domain_routes": _SMETA_DOMAIN_ROUTES,
        "collections": collections,
        "updated_at": time.time(),
    }
    notebook["prompt_excerpt"] = smeta_norm_rag_prompt_excerpt(notebook)
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
    lines.extend([
        "Навигация РИМ/ГЭСН: сначала определи семейство работ и измеритель, потом ищи норму; "
        "если единица нормы не совпадает с физическим объёмом, не bind-ить молча.",
        "Типовые вопросы применимости: земляные работы — группа грунта, глубина, крепления, ширина/сечение; "
        "металл — масса элемента и способ монтажа; инженерка — раздел ВК/ОВ/ЭОМ/СС, трассы и оборудование.",
        "Если пользователь разрешил сценарий по допущениям, допущения можно предложить, но пометить как сценарий; "
        "без такого разрешения спросить параметры.",
    ])
    lines.append("Правило: модель выбирает область работ; нормы/объёмы/деньги подтверждают инструменты.")
    return "\n".join(lines)


def smeta_norm_rag_prompt_excerpt(notebook: dict[str, Any] | None = None) -> str:
    nb = notebook or build_smeta_norm_rag_notebook()
    lines = ["[Сметный RAG-блокнот: карта норм/ресурсов/цен, навигация НЕ evidence]"]
    payload = nb.get("norm_store") or {}
    by_base = payload.get("by_base_type") if isinstance(payload.get("by_base_type"), dict) else {}
    if payload:
        base_text = ", ".join(f"{k}: {v}" for k, v in sorted(by_base.items())) or "—"
        lines.append(
            f"Индекс норм: {payload.get('norm_count', 0)} норм; базы: {base_text}; "
            f"коллекций: {payload.get('collections', 0)}."
        )
    lines.append("Слои источников: " + "; ".join(
        f"{layer['title']} = {layer['role']}" for layer in (nb.get("source_layers") or [])[:6]
    ) + ".")
    lines.append("Маршруты по разделам:")
    for route in (nb.get("domain_routes") or [])[:8]:
        lines.append(
            f"- {route.get('domain')}: искать в {', '.join(route.get('keys') or [])}; "
            f"{route.get('route')}; осторожно: {route.get('caution')}"
        )
    available = [c for c in (nb.get("collections") or []) if c.get("status") == "available"]
    if available:
        lines.append("Доступные опорные сборники/коллекции:")
        for col in available[:12]:
            examples = [
                str(ex.get("code") or "")
                for ex in (col.get("examples") or [])[:2]
                if ex.get("code")
            ]
            lines.append(
                f"- {col.get('collection')}: {col.get('area')} · норм: {col.get('norms')} · "
                f"ед.: {', '.join((col.get('units') or [])[:4]) or '—'} · примеры шифров: {', '.join(examples) or '—'}"
            )
    lines.extend([
        "Порядок для модели: ВОР → база/сборник/таблица → сравнение условий → полный шифр в Обоснование → расчётный trace.",
        "Если полного шифра нет, не изображай priced_final: дай кандидат/добор или scenario с маркировкой.",
    ])
    return "\n".join(lines)


def service_source_notebooks() -> dict[str, Any]:
    gesn = build_gesn_notebook()
    smeta = build_smeta_norm_rag_notebook()
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
            },
            {
                "id": "smeta_norms",
                "name": smeta["name"],
                "context_role": smeta["context_role"],
                "is_evidence": smeta["is_evidence"],
                "notebook_summary": smeta["notebook_summary"],
                "source_layers": smeta["source_layers"],
                "domain_routes": smeta["domain_routes"],
                "collections": smeta["collections"],
                "prompt_excerpt": smeta["prompt_excerpt"],
            },
        ],
    }
