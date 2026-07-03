"""Typed dataset memory: navigation layer with provenance hooks.

The model-facing memory is not evidence. It helps the answerer choose files and
tools, while checked claims still come from chunks, tables, graph atoms or code
calculations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from backend.rag_config import rag_meta_db_path

TYPED_MEMORY_SCHEMA = "dataset_memory_v1"
FILE_CARD_SCHEMA = "file_card_v1"
EVIDENCE_ATOM_SCHEMA = "evidence_atom_v1"
DATASET_READER_SCHEMA_ID = "dataset_reader_map_v1"
DATASET_BRIEF_SCHEMA_ID = "dataset_brief_for_model_v1"
DATASET_TOPIC_MAP_SCHEMA_ID = "dataset_topic_map_v1"
DATASET_SECTION_MAP_SCHEMA_ID = "dataset_section_map_v1"
DATASET_TOPIC_SELECTION_SCHEMA_ID = "dataset_topic_selection_v1"

logger = logging.getLogger(__name__)

CONTENT_LAYER_LABELS = {
    "text": "текст",
    "graphics": "графика",
    "tables": "таблицы",
    "calculations": "расчёты",
    "technical_docs": "техничка",
    "drawings": "чертежи",
    "cad_bim": "BIM/CAD",
    "normative": "нормы",
    "estimate": "сметы",
}

SOURCE_LAYER_ROLES: dict[str, dict[str, str]] = {
    "text": {
        "role": "пояснения, требования, описания решений и договорные условия",
        "use_for": "широкие вопросы, паспорт объекта, технические решения, обоснования",
        "evidence_rule": "подтверждать вывод найденным фрагментом документа",
    },
    "tables": {
        "role": "строки спецификаций, ВОР, объёмы, перечни и числовые данные",
        "use_for": "сметы, ведомости, реестры, суммы, количества",
        "evidence_rule": "числа брать из строк таблицы и считать кодом",
    },
    "calculations": {
        "role": "сметы, ЛСР, расчёты, балансы и формулы",
        "use_for": "стоимость, расчётные итоги, сверка предыдущих оценок",
        "evidence_rule": "итог проверять расчётной трассой, не пересказывать как факт без сверки",
    },
    "technical_docs": {
        "role": "проектные и технические документы",
        "use_for": "контекст проекта, состав документации, технические параметры",
        "evidence_rule": "открывать целевой файл, а не отвечать по названию",
    },
    "drawings": {
        "role": "чертежи и графические комплекты",
        "use_for": "геометрия, марки, листы, схемы, места установки",
        "evidence_rule": "для геометрии нужен лист/таблица/распознанный фрагмент",
    },
    "graphics": {
        "role": "сканы, изображения, листы с графикой",
        "use_for": "визуальная проверка, листы, схемы, OCR",
        "evidence_rule": "не делать числовой вывод без OCR/табличной проверки",
    },
    "cad_bim": {
        "role": "модельные элементы, свойства, связи CAD/BIM",
        "use_for": "элементы, параметры, количества из модели, навигация по BIM/CAD",
        "evidence_rule": "подтверждать через graph/properties/source_ref",
    },
    "normative": {
        "role": "нормативные документы, требования, пункты, таблицы",
        "use_for": "нормоконтроль, требования, применимость, запреты/разрешения",
        "evidence_rule": "сначала документ, затем пункт/таблица, затем вывод",
    },
    "estimate": {
        "role": "сметные формы, ВОР, ЛСР и стоимостные таблицы",
        "use_for": "сметная структура, цены, разделы, прежние расчёты",
        "evidence_rule": "отделять форму/сценарий от priced_final",
    },
}

RETRIEVAL_ROUTE_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "project_overview",
        "when": "рассказать про проект, объект, корпус, состав документации",
        "prefer_layers": ["text", "technical_docs"],
        "prefer_roles": ["состав проекта", "пояснительная записка", "задание на проектирование"],
        "method": "сначала открыть паспортные/пояснительные документы, затем добрать таблицы и чертежи",
    },
    {
        "id": "estimate_or_cost",
        "when": "смета, стоимость, ВОР, ЛСР, цена, объёмы работ",
        "prefer_layers": ["tables", "calculations", "estimate", "text"],
        "prefer_roles": ["сметный расчёт", "ведомость", "спецификация", "пояснительная записка"],
        "method": "сначала ВОР/спецификация/ЛСР, затем нормы/цены/расчётная трасса",
    },
    {
        "id": "normative_answer",
        "when": "нормоконтроль, требования, СП/ГОСТ/СНиП, требуется или не требуется",
        "prefer_layers": ["normative", "text"],
        "require_layers": ["normative"],
        "prefer_roles": ["нормативный документ"],
        "method": "сначала документ-кандидат, затем пункт/подпункт/таблица, затем вывод",
    },
    {
        "id": "table_query",
        "when": "реестр, спецификация, ведомость, перечень, количество, таблица",
        "prefer_layers": ["tables", "calculations"],
        "prefer_roles": ["ведомость", "спецификация", "сметный расчёт"],
        "method": "искать табличный слой; суммы и проценты считать кодом",
    },
    {
        "id": "cad_bim_query",
        "when": "модель, BIM/CAD, элементы, свойства, марки, координаты",
        "prefer_layers": ["cad_bim", "drawings", "graphics"],
        "prefer_roles": ["чертёжный комплект", "документ"],
        "method": "искать graph/properties/projection, затем связанные документы",
    },
]

_TABLE_EXTS = {".xls", ".xlsx", ".xlsm", ".csv"}
_CAD_EXTS = {".dwg", ".dxf", ".ifc", ".ifczip", ".rvt", ".rfa", ".nwc"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
_DRAWING_MARKS = {
    "ар", "ас", "кр", "кж", "км", "кмд", "ов", "вк", "нвк", "эом", "эм", "сс", "апс", "соуэ",
    "пзу", "гп", "ios", "иос",
}
_TECH_RE = re.compile(
    r"(паспорт|руководств|инструкц|техническ|технич|ту\b|задани[ея]|пояснительн|пз\b|состав\s+проекта)",
    re.I,
)
_CALC_RE = re.compile(r"(расчет|расч[её]т|калькуляц|лср|кац|баланс|формул|смет|стоимост|итого)", re.I)
_SPEC_RE = re.compile(r"(спецификац|ведомост|вор\b|оборудован|материал|таблиц)", re.I)
_NORM_RE = re.compile(r"(гост|сп\s*\d|снип|санпин|гэсн|фер|тер|норматив|свод\s+правил)", re.I)
_SMETA_NORM_RE = re.compile(
    r"(smeta_ru_norm|fsnb|фснб|gesn|гэсн|fer|фер|fsem|фсэм|fsbc|фсбц|fssc|фссц|fgis|фгис)",
    re.I,
)
_SERVICE_NOISE_RE = re.compile(
    r"(^|[/\\])(?:\.pdf_preprocess_state\.json|00_.*|.*(?:manifest|dataset_card|group_classifier|classifier|preprocess_state).*)$",
    re.I,
)
_SMETA_NESTED_ROLE_HINTS: tuple[tuple[str, str], ...] = (
    ("a_srf_f", "таблица норм/расценок ФСНБ"),
    ("a_srf_tr", "таблица ресурсов нормы"),
    ("a_srf_vr", "таблица видов работ/разделов норм"),
    ("a_f3_vr", "иерархия разделов и таблиц ФСНБ"),
    ("b_normtype", "тип нормативной базы"),
    ("b_group", "группы нормативного классификатора"),
    ("b_putname", "наименования путей/разделов"),
    ("level_cost", "ценовой уровень/стоимостные параметры"),
    ("level_compose", "состав уровня/ресурсная структура"),
    ("level_params", "параметры уровня/таблицы"),
    ("level_vc", "вспомогательная таблица связей уровня"),
    ("arctype", "тип архива/служебный классификатор"),
)
_RUNNING_READER_TASKS: set[str] = set()

TOPIC_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "project_overview",
        "label": "паспорт объекта и состав проекта",
        "terms": ("состав проекта", "пояснительная записка", "паспорт", "тэп", "исходные данные", "задание"),
        "prefer_layers": ("text", "technical_docs"),
    },
    {
        "id": "fire_alarm_automation",
        "label": "пожарная сигнализация и противопожарная автоматика",
        "terms": (
            "пожар", "пожарная сигнализация", "апс", "аупс", "опс", "противопожарная автоматика",
            "пожаротушение", "извещатель", "дым", "соуэ", "противодым", "пдв", "сту",
        ),
        "prefer_layers": ("text", "technical_docs", "normative", "tables"),
    },
    {
        "id": "security_low_current",
        "label": "слаботочные системы и безопасность",
        "terms": ("ксб", "скуд", "сот", "видеонаблюдение", "охранная сигнализация", "слаботоч", "опс"),
        "prefer_layers": ("text", "technical_docs", "tables"),
    },
    {
        "id": "hvac_smoke_control",
        "label": "ОВ/противодымная вентиляция",
        "terms": ("ов", "вентиляция", "противодым", "дымоудаление", "подпор", "пдв", "сп 7.13130"),
        "prefer_layers": ("text", "technical_docs", "normative", "drawings"),
    },
    {
        "id": "electrical_power",
        "label": "электроснабжение и питание",
        "terms": ("эом", "эм", "электроснабжение", "электрооборудование", "питание", "кабель", "щит"),
        "prefer_layers": ("text", "technical_docs", "tables", "drawings"),
    },
    {
        "id": "water_fire",
        "label": "водоснабжение и пожаротушение",
        "terms": ("вк", "водопровод", "пожаротушение", "спринклер", "внутренний противопожарный", "насос"),
        "prefer_layers": ("text", "technical_docs", "tables", "drawings"),
    },
    {
        "id": "estimate_cost",
        "label": "ВОР, сметы и стоимость",
        "terms": ("вор", "лср", "смета", "стоимость", "цена", "гэсн", "рим", "ресурсы", "фгис"),
        "prefer_layers": ("tables", "calculations", "estimate", "normative"),
    },
    {
        "id": "normative_requirements",
        "label": "нормы и требования",
        "terms": ("сп ", "гост", "снип", "норматив", "требования", "пункт", "таблица", "приложение"),
        "prefer_layers": ("normative", "text"),
    },
)

DATASET_READER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema",
        "corpus_kind",
        "reader_summary",
        "where_to_look",
        "file_roles",
        "known_gaps",
        "answer_guidance",
        "confidence",
    ],
    "properties": {
        "schema": {"type": "string", "enum": [DATASET_READER_SCHEMA_ID]},
        "corpus_kind": {
            "type": "string",
            "enum": ["project", "normative", "estimate", "technical_catalog", "mixed", "unknown"],
        },
        "reader_summary": {"type": "string"},
        "where_to_look": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["question_type", "target_files", "reason"],
                "properties": {
                    "question_type": {"type": "string"},
                    "target_files": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
                    "reason": {"type": "string"},
                },
            },
            "maxItems": 16,
        },
        "file_roles": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["file_name", "role", "what_inside", "confidence"],
                "properties": {
                    "file_name": {"type": "string"},
                    "role": {"type": "string"},
                    "what_inside": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
            "maxItems": 40,
        },
        "known_gaps": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "answer_guidance": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


def _connect(meta_db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(meta_db_path or rag_meta_db_path())
    conn.row_factory = sqlite3.Row
    ensure_typed_memory_schema(conn)
    return conn


def ensure_typed_memory_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dataset_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            content_signature TEXT NOT NULL,
            document_count INTEGER NOT NULL DEFAULT 0,
            indexed_count INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            UNIQUE(dataset_id, revision_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dataset_memory (
            dataset_id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL,
            schema TEXT NOT NULL,
            memory_json TEXT NOT NULL,
            reader_status TEXT NOT NULL DEFAULT 'bootstrap',
            is_evidence INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS file_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_kind TEXT NOT NULL DEFAULT 'document',
            content_layers_json TEXT NOT NULL DEFAULT '[]',
            document_role TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            key_entities_json TEXT NOT NULL DEFAULT '[]',
            confidence REAL NOT NULL DEFAULT 0.5,
            provenance_json TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL,
            UNIQUE(dataset_id, revision_id, file_name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence_atoms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            atom_kind TEXT NOT NULL,
            value_text TEXT NOT NULL DEFAULT '',
            value_num REAL,
            unit TEXT NOT NULL DEFAULT '',
            entity_refs_json TEXT NOT NULL DEFAULT '[]',
            source_ref TEXT NOT NULL DEFAULT '',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            confidence REAL NOT NULL DEFAULT 0.5,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_cards_dataset ON file_cards(dataset_id, revision_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atoms_dataset ON evidence_atoms(dataset_id, revision_id)")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _operator_guidance_from_profiles(conn: sqlite3.Connection, dataset_id: str) -> dict[str, Any]:
    try:
        row = conn.execute(
            "SELECT profile_json FROM les_dataset_profiles WHERE dataset_id=?",
            (dataset_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return {}
    profile = _loads(row["profile_json"], {}) if row else {}
    if not isinstance(profile, dict):
        return {}
    guidance = " ".join(str(profile.get("operator_guidance") or "").replace("\r", "\n").split())[:4000].strip()
    if not guidance:
        return {}
    return {
        "operator_guidance": guidance,
        "operator_guidance_role": "navigation_not_evidence",
        "operator_guidance_updated_at": profile.get("operator_guidance_updated_at") or 0,
    }


def _documents(conn: sqlite3.Connection, dataset_id: str) -> list[dict[str, Any]]:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    if not columns:
        return []

    def _expr(name: str, default: str = "''") -> str:
        return f"COALESCE({name}, {default})" if name in columns else default

    rows = conn.execute(
        f"""
        SELECT dataset_id, file_name, status,
               {_expr("chunk_count", "0")} AS chunk_count,
               {_expr("doc_type")} AS doc_type,
               {_expr("content_type")} AS content_type,
               {_expr("domain")} AS domain,
               {_expr("route_dataset")} AS route_dataset,
               {_expr("pipeline")} AS pipeline,
               {_expr("source_path")} AS source_path
        FROM documents
        WHERE dataset_id=?
        ORDER BY file_name
        """,
        (dataset_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _content_signature(docs: list[dict[str, Any]]) -> str:
    payload = [
        {
            "file_name": d.get("file_name", ""),
            "status": d.get("status", ""),
            "chunk_count": int(d.get("chunk_count") or 0),
            "doc_type": d.get("doc_type", ""),
            "content_type": d.get("content_type", ""),
            "pipeline": d.get("pipeline", ""),
        }
        for d in docs
    ]
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()[:16]


def _add(layers: list[str], *items: str) -> None:
    for item in items:
        if item and item not in layers:
            layers.append(item)


def _is_smeta_norm_source(file_name: str, domain: str, doc_type: str) -> bool:
    probe = f"{domain} {doc_type} {file_name}".casefold().replace("ё", "е")
    return domain.startswith("SMETA_RU_NORM") or bool(_SMETA_NORM_RE.search(probe))


def _is_service_noise_file(file_name: str) -> bool:
    name = str(file_name or "").strip()
    if not name:
        return False
    low_name = name.casefold().replace("ё", "е")
    base = Path(low_name).name
    return bool(_SERVICE_NOISE_RE.search(low_name) or base in {"manifest.json", "index.json"})


def _service_noise_penalty(card_or_file: dict[str, Any] | str) -> int:
    file_name = card_or_file if isinstance(card_or_file, str) else str(card_or_file.get("file_name") or "")
    return 10_000 if _is_service_noise_file(file_name) else 0


def _smeta_nested_role_hint(probe: str) -> str | None:
    normalized = re.sub(r"[^0-9a-zа-я]+", "_", probe.casefold().replace("ё", "е"))
    for token, role in _SMETA_NESTED_ROLE_HINTS:
        if token in normalized:
            return role
    return None


def _dedupe_terms(items: list[str], *, limit: int = 12) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        term = re.sub(r"\s+", " ", str(item or "").strip())
        if not term:
            continue
        key = term.casefold().replace("ё", "е")
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= limit:
            break
    return out


def _navigation_terms_for_file(file_name: str, role: str, layers: list[str], doc_type: str = "", domain: str = "") -> list[str]:
    """Human retrieval aliases for model navigation, not evidence."""
    probe = f"{domain} {doc_type} {file_name} {role}".casefold().replace("ё", "е")
    terms: list[str] = []
    role_low = role.casefold().replace("ё", "е")
    if "normative" in layers or _is_smeta_norm_source(file_name, domain, doc_type):
        terms.extend(["нормативная база", "норма", "шифр", "сборник", "таблица"])
    if "таблица норм/расценок" in role_low or "a_srf_f" in probe:
        terms.extend(["нормы", "расценки", "шифр нормы", "наименование нормы", "единица измерения", "ГЭСН", "ФЕР"])
    if "таблица ресурсов" in role_low or "a_srf_tr" in probe:
        terms.extend(["ресурсы нормы", "затраты труда", "машины", "материалы", "ресурсный код", "состав ресурсов"])
    if "видов работ" in role_low or "иерархия" in role_low or "a_srf_vr" in probe or "a_f3_vr" in probe:
        terms.extend(["вид работ", "раздел", "таблица", "сборник", "навигация по нормам"])
    if "тип нормативной базы" in role_low or "b_normtype" in probe:
        terms.extend(["редакция базы", "тип нормы", "ФСНБ-2022"])
    if "ценовой уровень" in role_low or "level_cost" in probe:
        terms.extend(["ценовой уровень", "стоимость", "цена ресурса", "индекс", "ФГИС ЦС"])
    if "фсэм" in role_low:
        terms.extend(["машины", "механизмы", "машино-час", "ФСЭМ"])
    if "фсбц материалы" in role_low:
        terms.extend(["материалы", "базовая цена материалов", "ФСБЦм"])
    if "фсбц оборудование" in role_low:
        terms.extend(["оборудование", "базовая цена оборудования", "ФСБЦо"])
    if "сплит" in role_low or "фгис" in role_low or "pricebook" in probe:
        terms.extend(["ФГИС ЦС", "сплит-форма", "цены ресурсов", "регион", "квартал", "pricebook"])
    if "ведомость" in role_low:
        terms.extend(["ВОР", "объёмы работ", "ведомость", "количество", "единица"])
    if "спецификация" in role_low:
        terms.extend(["спецификация", "поставка", "материалы", "оборудование", "монтаж"])
    if "сметный расчет" in role_low or "estimate" in layers:
        terms.extend(["ЛСР", "смета", "стоимость", "позиция", "обоснование"])
    if "состав проекта" in role_low:
        terms.extend(["состав проекта", "тома", "разделы", "комплект документации"])
    if "пояснительная записка" in role_low:
        terms.extend(["пояснительная записка", "технические решения", "исходные данные"])
    if "чертеж" in role_low or "drawings" in layers:
        terms.extend(["лист", "чертёж", "схема", "марка", "геометрия"])
    return _dedupe_terms(terms)


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold().replace("ё", "е")).strip()


def _topic_match_score(probe: str, terms: tuple[str, ...]) -> tuple[int, list[str]]:
    score = 0
    hits: list[str] = []
    for term in terms:
        normalized = _norm_text(term)
        if not normalized:
            continue
        if normalized in probe:
            hits.append(term)
            score += 8 if " " in normalized else 5
            continue
        if normalized.endswith(" "):
            continue
        token = re.escape(normalized)
        if re.search(rf"(^|[^0-9a-zа-я]){token}", probe):
            hits.append(term)
            score += 4
    return score, _dedupe_terms(hits, limit=8)


def _lexical_section_signals(conn: sqlite3.Connection, dataset_id: str, *, limit: int = 600) -> list[dict[str, Any]]:
    """Bounded section/heading signals from lexical_chunks. No source-file reads."""
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()
    }
    if "lexical_chunks" not in tables:
        return []
    try:
        rows = conn.execute(
            """
            SELECT
                doc_name,
                COALESCE(NULLIF(section_heading,''), NULLIF(parent_heading,''), '') AS heading,
                COUNT(*) AS chunks
            FROM lexical_chunks
            WHERE dataset_id=?
              AND COALESCE(NULLIF(section_heading,''), NULLIF(parent_heading,''), '') <> ''
            GROUP BY doc_name, heading
            ORDER BY chunks DESC, doc_name, heading
            LIMIT ?
            """,
            (dataset_id, int(limit)),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        heading = str(row["heading"] or "").strip()
        doc_name = str(row["doc_name"] or "").strip()
        if not heading or not doc_name:
            continue
        out.append({"file_name": doc_name, "heading": heading, "chunk_count": int(row["chunks"] or 0)})
    return out


def _build_section_map(dataset_id: str, section_signals: list[dict[str, Any]], cards: list[dict[str, Any]]) -> dict[str, Any]:
    by_file: dict[str, list[dict[str, Any]]] = {}
    for signal in section_signals:
        file_name = str(signal.get("file_name") or "")
        heading = str(signal.get("heading") or "").strip()
        if not file_name or not heading:
            continue
        by_file.setdefault(file_name, []).append(
            {
                "heading": heading[:220],
                "chunk_count": int(signal.get("chunk_count") or 0),
                "topic_hints": _section_topic_hints(heading),
            }
        )

    card_names = {str(card.get("file_name") or "") for card in cards}
    files = []
    for file_name, sections in sorted(
        by_file.items(),
        key=lambda item: (-sum(int(sec.get("chunk_count") or 0) for sec in item[1]), item[0]),
    )[:80]:
        if card_names and file_name not in card_names:
            # Lexical may contain legacy aliases. Keep only sections that can be opened via doc_filter.
            continue
        sections.sort(key=lambda item: (-int(item.get("chunk_count") or 0), str(item.get("heading") or "")))
        files.append({"file_name": file_name, "sections": sections[:12]})

    return {
        "schema": DATASET_SECTION_MAP_SCHEMA_ID,
        "context_role": "navigation",
        "is_evidence": False,
        "dataset_id": dataset_id,
        "source": "lexical_chunks.section_heading",
        "files": files,
        "coverage": {
            "files_with_sections": len(files),
            "section_count": sum(len(item.get("sections") or []) for item in files),
        },
        "rule": "section_map guides target retrieval; final claims require retrieved source fragments",
    }


def _section_topic_hints(text: str) -> list[str]:
    probe = _norm_text(text)
    hints: list[str] = []
    for topic in TOPIC_DEFINITIONS:
        score, _hits = _topic_match_score(probe, tuple(topic.get("terms") or ()))
        if score:
            hints.append(str(topic.get("label") or topic.get("id") or ""))
    return _dedupe_terms(hints, limit=5)


def _build_topic_map(
    dataset_id: str,
    cards: list[dict[str, Any]],
    section_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    cards_by_name = {str(card.get("file_name") or ""): card for card in cards}
    topics: list[dict[str, Any]] = []
    for topic in TOPIC_DEFINITIONS:
        terms = tuple(str(term) for term in (topic.get("terms") or ()))
        prefer_layers = {str(layer) for layer in (topic.get("prefer_layers") or ())}
        file_hits: list[tuple[int, dict[str, Any], list[str]]] = []
        section_hits: list[tuple[int, dict[str, Any], list[str]]] = []

        for card in cards:
            probe = _norm_text(
                " ".join(
                    [
                        str(card.get("file_name") or ""),
                        str(card.get("document_role") or ""),
                        " ".join(str(term) for term in (card.get("navigation_terms") or [])),
                        str(card.get("summary") or ""),
                    ]
                )
            )
            score, hits = _topic_match_score(probe, terms)
            card_layers = {str(layer) for layer in (card.get("content_layers") or [])}
            if score and card_layers.intersection(prefer_layers):
                score += 4
            if score:
                score += min(6, int(card.get("chunk_count") or 0) // 80)
                score -= _service_noise_penalty(card)
                file_hits.append((score, card, hits))

        for signal in section_signals:
            heading = str(signal.get("heading") or "")
            file_name = str(signal.get("file_name") or "")
            card = cards_by_name.get(file_name)
            if not card:
                continue
            probe = _norm_text(f"{file_name} {heading}")
            score, hits = _topic_match_score(probe, terms)
            if not score:
                continue
            score += min(5, int(signal.get("chunk_count") or 0))
            section_hits.append((score, signal, hits))

        file_hits.sort(key=lambda item: (-item[0], str(item[1].get("file_name") or "")))
        section_hits.sort(key=lambda item: (-item[0], str(item[1].get("file_name") or ""), str(item[1].get("heading") or "")))
        if not file_hits and not section_hits:
            continue

        top_files = []
        seen_files: set[str] = set()
        for score, card, hits in file_hits[:10]:
            file_name = str(card.get("file_name") or "")
            if file_name in seen_files:
                continue
            seen_files.add(file_name)
            top_files.append(
                {
                    "file_name": file_name,
                    "role": card.get("document_role") or "документ",
                    "layers": list(card.get("content_layers") or []),
                    "navigation_terms": list(card.get("navigation_terms") or [])[:8],
                    "matched_terms": hits,
                    "chunk_count": int(card.get("chunk_count") or 0),
                    "score": int(score),
                }
            )
        top_sections = [
            {
                "file_name": str(signal.get("file_name") or ""),
                "heading": str(signal.get("heading") or "")[:220],
                "matched_terms": hits,
                "chunk_count": int(signal.get("chunk_count") or 0),
                "score": int(score),
            }
            for score, signal, hits in section_hits[:12]
        ]
        confidence = 0.35
        if top_sections:
            confidence += 0.25
        if top_files:
            confidence += 0.2
        if len(top_files) >= 3 or len(top_sections) >= 3:
            confidence += 0.1
        topics.append(
            {
                "id": topic["id"],
                "label": topic["label"],
                "query_aliases": list(terms)[:12],
                "top_files": top_files,
                "top_sections": top_sections,
                "confidence": round(min(confidence, 0.9), 2),
                "is_evidence": False,
            }
        )

    topics.sort(
        key=lambda item: (
            -float(item.get("confidence") or 0),
            -len(item.get("top_sections") or []),
            -len(item.get("top_files") or []),
            str(item.get("label") or ""),
        )
    )
    return {
        "schema": DATASET_TOPIC_MAP_SCHEMA_ID,
        "context_role": "navigation",
        "is_evidence": False,
        "dataset_id": dataset_id,
        "topics": topics[:24],
        "rule": "topic_map selects candidate files/sections; answers still need retrieved chunks/tables/graph/calculation trace",
    }


def select_topic_retrieval_plan(
    memories: list[dict[str, Any]],
    question: str,
    *,
    max_topics: int = 2,
    max_files: int = 10,
    max_sections: int = 12,
) -> dict[str, Any]:
    """Pick dataset topic files for a targeted retrieval pass.

    This is navigation only: it chooses candidate files/sections from typed
    memory, then normal retrieval must still fetch source chunks.
    """
    q = _norm_text(question)
    if not q:
        return {
            "schema": DATASET_TOPIC_SELECTION_SCHEMA_ID,
            "context_role": "navigation",
            "is_evidence": False,
            "selected_topics": [],
            "selected_files": [],
            "selected_sections": [],
            "fallback": "wide_retrieval",
        }

    topic_hits: list[tuple[int, str, dict[str, Any], list[str]]] = []
    for memory in memories:
        memory = _ensure_memory_navigation(memory or {})
        dataset_id = str(memory.get("dataset_id") or "")
        topic_map = memory.get("topic_map") if isinstance(memory.get("topic_map"), dict) else {}
        for topic in topic_map.get("topics") or []:
            aliases = [
                str(topic.get("id") or ""),
                str(topic.get("label") or ""),
                *[str(alias) for alias in (topic.get("query_aliases") or [])],
            ]
            score, hits = _topic_match_score(q, tuple(aliases))
            if not score:
                continue
            score += int(float(topic.get("confidence") or 0) * 10)
            score += min(4, len(topic.get("top_sections") or []))
            score += min(3, len(topic.get("top_files") or []))
            topic_hits.append((score, dataset_id, topic, hits))

    topic_hits.sort(key=lambda item: (-item[0], str(item[2].get("label") or ""), item[1]))
    selected_topics: list[dict[str, Any]] = []
    selected_files: list[dict[str, Any]] = []
    selected_sections: list[dict[str, Any]] = []
    seen_topics: set[tuple[str, str]] = set()
    seen_files: set[str] = set()
    seen_sections: set[tuple[str, str]] = set()

    def _add_file(file_name: str, *, dataset_id: str, topic_id: str, reason: str, heading: str = "") -> None:
        clean_name = str(file_name or "").strip()
        if not clean_name or clean_name in seen_files or len(selected_files) >= max_files:
            return
        seen_files.add(clean_name)
        item = {
            "dataset_id": dataset_id,
            "file_name": clean_name,
            "topic_id": topic_id,
            "reason": reason,
        }
        if heading:
            item["section_heading"] = heading[:220]
        selected_files.append(item)

    for score, dataset_id, topic, hits in topic_hits:
        topic_id = str(topic.get("id") or "")
        topic_key = (dataset_id, topic_id)
        if topic_key in seen_topics:
            continue
        seen_topics.add(topic_key)
        selected_topics.append(
            {
                "dataset_id": dataset_id,
                "id": topic_id,
                "label": topic.get("label") or topic_id,
                "matched_terms": hits,
                "score": int(score),
                "confidence": topic.get("confidence"),
            }
        )
        for section in topic.get("top_sections") or []:
            file_name = str(section.get("file_name") or "").strip()
            heading = str(section.get("heading") or "").strip()
            section_key = (file_name, heading)
            if not file_name or section_key in seen_sections:
                continue
            seen_sections.add(section_key)
            if len(selected_sections) < max_sections:
                selected_sections.append(
                    {
                        "dataset_id": dataset_id,
                        "file_name": file_name,
                        "heading": heading[:220],
                        "topic_id": topic_id,
                        "matched_terms": list(section.get("matched_terms") or [])[:8],
                    }
                )
            _add_file(
                file_name,
                dataset_id=dataset_id,
                topic_id=topic_id,
                reason="topic_section",
                heading=heading,
            )
        for file_item in topic.get("top_files") or []:
            _add_file(
                str(file_item.get("file_name") or ""),
                dataset_id=dataset_id,
                topic_id=topic_id,
                reason="topic_file",
            )
        if len(selected_topics) >= max_topics:
            break

    return {
        "schema": DATASET_TOPIC_SELECTION_SCHEMA_ID,
        "context_role": "navigation",
        "is_evidence": False,
        "question_terms": q[:400],
        "selected_topics": selected_topics,
        "selected_files": selected_files,
        "selected_sections": selected_sections,
        "fallback": "wide_retrieval",
        "rule": "selected files/sections guide doc_filter retrieval; final answer still requires retrieved source chunks",
    }


def infer_file_typing(doc: dict[str, Any]) -> dict[str, Any]:
    """Multi-label file typing from current metadata and file naming signals."""
    file_name = str(doc.get("file_name") or "")
    name = Path(file_name).name
    low = file_name.casefold().replace("ё", "е")
    ext = Path(name).suffix.lower()
    doc_type = str(doc.get("doc_type") or "").upper()
    content_type = str(doc.get("content_type") or "").lower()
    domain = str(doc.get("domain") or "").upper()
    pipeline = str(doc.get("pipeline") or "").lower()
    smeta_norm_source = _is_smeta_norm_source(file_name, domain, doc_type)
    layers: list[str] = []

    if ext in _TABLE_EXTS or content_type == "table" or doc_type in {"TABLE", "SPEC", "KS2"}:
        _add(layers, "tables")
    if ext in _CAD_EXTS or content_type == "cad_bim" or doc_type == "CAD_BIM" or domain == "CAD_BIM":
        _add(layers, "cad_bim", "graphics")
    if ext in _IMAGE_EXTS or content_type == "scan":
        _add(layers, "graphics")
    if ext == ".pdf" or "markdown_pdf_tables" in pipeline:
        _add(layers, "text")
        if content_type in {"mixed", "scan"}:
            _add(layers, "graphics")
    if ext in {".doc", ".docx", ".txt", ".md"} or content_type in {"text", "mixed", "email"}:
        _add(layers, "text")
    if doc_type == "NORMATIVE" or domain.startswith("NTD_") or smeta_norm_source or _NORM_RE.search(low):
        _add(layers, "normative", "text")
    if not smeta_norm_source and (doc_type == "SMETA" or "SMETA" in domain or _CALC_RE.search(low)):
        _add(layers, "calculations", "estimate")
    if _SPEC_RE.search(low):
        _add(layers, "tables", "technical_docs")
    if _TECH_RE.search(low):
        _add(layers, "technical_docs", "text")
    if any(mark in low.split("/")[-1].replace("_", " ").replace("-", " ").split() for mark in _DRAWING_MARKS):
        _add(layers, "drawings", "graphics", "technical_docs")
    if not layers:
        _add(layers, "text")

    if "cad_bim" in layers:
        file_kind = "model_or_cad"
    elif smeta_norm_source or "normative" in layers:
        file_kind = "normative"
    elif "estimate" in layers:
        file_kind = "estimate"
    elif "drawings" in layers:
        file_kind = "drawing_set"
    elif "tables" in layers and layers == ["tables"]:
        file_kind = "table"
    elif "technical_docs" in layers:
        file_kind = "technical_document"
    else:
        file_kind = "document"

    role = _document_role(low, layers, doc_type, domain)
    navigation_terms = _navigation_terms_for_file(file_name, role, layers, doc_type, domain)
    return {
        "file_kind": file_kind,
        "content_layers": layers,
        "content_layer_labels": [CONTENT_LAYER_LABELS.get(layer, layer) for layer in layers],
        "document_role": role,
        "navigation_terms": navigation_terms,
        "source_granularity": _source_granularity(layers),
        "confidence": 0.78 if doc_type or content_type else 0.58,
        "classified_by": "metadata_name_bootstrap",
    }


def _document_role(low_name: str, layers: list[str], doc_type: str, domain: str = "") -> str:
    smeta_norm_source = _is_smeta_norm_source(low_name, domain, doc_type)
    if smeta_norm_source:
        probe = f"{domain} {low_name}".casefold().replace("ё", "е")
        if nested_role := _smeta_nested_role_hint(probe):
            return nested_role
        if "split" in probe or "сплит" in probe or "fgis" in probe or "фгис" in probe:
            return "сплит-форма/ФГИС"
        if "gesnmr" in probe or "гэснмр" in probe:
            return "ГЭСНмр"
        if "gesnm" in probe or "гэснм" in probe:
            return "ГЭСНм"
        if "gesnp" in probe or "гэснп" in probe:
            return "ГЭСНп"
        if "gesnr" in probe or "гэснр" in probe:
            return "ГЭСНр"
        if "gesn" in probe or "гэсн" in probe:
            return "ГЭСН"
        if "fermr" in probe or "фермр" in probe:
            return "ФЕРмр"
        if "ferm" in probe or "ферм" in probe:
            return "ФЕРм"
        if "ferp" in probe or "ферп" in probe:
            return "ФЕРп"
        if "ferr" in probe or "ферр" in probe:
            return "ФЕРр"
        if "fer" in probe or "фер" in probe:
            return "ФЕР"
        if "fsem" in probe or "fsbcmm" in probe or "фсэм" in probe:
            return "ФСЭМ"
        if "fsbco" in probe or "fssco" in probe or "оборуд" in probe:
            return "ФСБЦ оборудование"
        if "fsbcm" in probe or "fsscm" in probe or "материал" in probe:
            return "ФСБЦ материалы"
        return "сметно-нормативная база"
    if "состав" in low_name and "проект" in low_name:
        return "состав проекта"
    if "пояснительн" in low_name or re.search(r"(^|[/_\-\s])пз($|[/_\-\s.])", low_name):
        return "пояснительная записка"
    if "задани" in low_name and "проект" in low_name:
        return "задание на проектирование"
    if "спецификац" in low_name:
        return "спецификация"
    if "ведомост" in low_name or "вор" in low_name:
        return "ведомость"
    if doc_type == "NORMATIVE":
        return "нормативный документ"
    if "cad_bim" in layers:
        return "модель/графика"
    if "estimate" in layers:
        return "сметный расчёт"
    if "drawings" in layers:
        return "чертёжный комплект"
    return "документ"


def _source_granularity(layers: list[str]) -> str:
    if "cad_bim" in layers:
        return "element_property"
    if "tables" in layers or "calculations" in layers:
        return "table_row_or_cell"
    if "drawings" in layers or "graphics" in layers:
        return "page_region"
    return "chunk"


def chunk_payload_typing(file_name: str, route_metadata: dict[str, Any] | None, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Typed metadata for Qdrant/lexical payloads."""
    doc = dict(route_metadata or {})
    doc["file_name"] = file_name
    payload = payload or {}
    if payload.get("type") == "table_row":
        doc["content_type"] = "table"
    typing = infer_file_typing(doc)
    source_granularity = typing["source_granularity"]
    if payload.get("type") == "table_row":
        source_granularity = "table_row"
    elif payload.get("mail_node_kind"):
        source_granularity = "message_part"
    return {
        "file_kind": typing["file_kind"],
        "content_layers": typing["content_layers"],
        "content_layer_labels": typing["content_layer_labels"],
        "document_role": typing["document_role"],
        "navigation_terms": typing.get("navigation_terms") or [],
        "source_granularity": source_granularity,
        "typed_by": typing["classified_by"],
    }


def _file_summary(doc: dict[str, Any], typing: dict[str, Any]) -> str:
    labels = ", ".join(typing.get("content_layer_labels") or [])
    role = typing.get("document_role") or "документ"
    chunks = int(doc.get("chunk_count") or 0)
    status = str(doc.get("status") or "")
    return f"{role}; слои: {labels}; статус индекса {status}; чанков {chunks}"


def build_typed_dataset_memory(
    dataset_id: str,
    *,
    force: bool = False,
    meta_db_path: str | None = None,
) -> dict[str, Any]:
    """Build/update typed memory and file cards. No reindex, no vector writes."""
    now = time.time()
    with _connect(meta_db_path) as conn:
        docs = _documents(conn, dataset_id)
        signature = _content_signature(docs)
        revision_id = f"rev-{signature}"
        existing = conn.execute(
            "SELECT memory_json FROM dataset_memory WHERE dataset_id=? AND revision_id=?",
            (dataset_id, revision_id),
        ).fetchone()
        if existing and not force:
            return _ensure_memory_navigation(_loads(existing["memory_json"], {}))

        indexed_count = sum(1 for d in docs if str(d.get("status") or "") == "INDEXED")
        chunk_count = sum(int(d.get("chunk_count") or 0) for d in docs)
        conn.execute(
            """
            INSERT OR IGNORE INTO dataset_revisions
                (dataset_id, revision_id, content_signature, document_count, indexed_count, chunk_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (dataset_id, revision_id, signature, len(docs), indexed_count, chunk_count, now),
        )

        cards = []
        by_layer: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        roles: dict[str, int] = {}
        for doc in docs:
            typing = infer_file_typing(doc)
            for layer in typing["content_layers"]:
                by_layer[layer] = by_layer.get(layer, 0) + 1
            by_kind[typing["file_kind"]] = by_kind.get(typing["file_kind"], 0) + 1
            role = typing["document_role"]
            roles[role] = roles.get(role, 0) + 1
            card = {
                "schema": FILE_CARD_SCHEMA,
                "dataset_id": dataset_id,
                "revision_id": revision_id,
                "file_name": str(doc.get("file_name") or ""),
                "status": str(doc.get("status") or ""),
                "chunk_count": int(doc.get("chunk_count") or 0),
                "file_kind": typing["file_kind"],
                "content_layers": typing["content_layers"],
                "content_layer_labels": typing["content_layer_labels"],
                "document_role": role,
                "navigation_terms": typing.get("navigation_terms") or [],
                "summary": _file_summary(doc, typing),
                "key_entities": [],
                "confidence": typing["confidence"],
                "provenance": {
                    "source": "metadb.documents",
                    "classified_by": typing["classified_by"],
                    "doc_type": str(doc.get("doc_type") or ""),
                    "content_type": str(doc.get("content_type") or ""),
                    "domain": str(doc.get("domain") or ""),
                    "pipeline": str(doc.get("pipeline") or ""),
                },
            }
            cards.append(card)
            conn.execute(
                """
                INSERT INTO file_cards
                    (dataset_id, revision_id, file_name, file_kind, content_layers_json, document_role,
                     summary, key_entities_json, confidence, provenance_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_id, revision_id, file_name) DO UPDATE SET
                    file_kind=excluded.file_kind,
                    content_layers_json=excluded.content_layers_json,
                    document_role=excluded.document_role,
                    summary=excluded.summary,
                    key_entities_json=excluded.key_entities_json,
                    confidence=excluded.confidence,
                    provenance_json=excluded.provenance_json,
                    updated_at=excluded.updated_at
                """,
                (
                    dataset_id,
                    revision_id,
                    card["file_name"],
                    card["file_kind"],
                    _json(card["content_layers"]),
                    card["document_role"],
                    card["summary"],
                    _json(card["key_entities"]),
                    card["confidence"],
                    _json(card["provenance"]),
                    now,
                ),
            )

        section_signals = _lexical_section_signals(conn, dataset_id)
        source_layers = _source_layers_from_counts(by_layer)
        retrieval_routes = _retrieval_routes_for_dataset(cards, source_layers)
        source_graph = _source_graph_for_dataset(dataset_id, cards, source_layers)
        section_map = _build_section_map(dataset_id, section_signals, cards)
        topic_map = _build_topic_map(dataset_id, cards, section_signals)
        operator_guidance = _operator_guidance_from_profiles(conn, dataset_id)
        memory = {
            "schema": TYPED_MEMORY_SCHEMA,
            "dataset_id": dataset_id,
            "revision_id": revision_id,
            "context_role": "navigation",
            "is_evidence": False,
            "reader_status": "bootstrap",
            "reader_note": (
                "Typed memory is a navigation map. Facts in final answers must still come "
                "from retrieved chunks, table rows, graph atoms or calculation services."
            ),
            "document_count": len(docs),
            "indexed_count": indexed_count,
            "chunk_count": chunk_count,
            "data_layers": [
                {"id": layer, "label": CONTENT_LAYER_LABELS.get(layer, layer), "files": count}
                for layer, count in sorted(by_layer.items(), key=lambda item: (-item[1], item[0]))
            ],
            "file_kinds": [
                {"id": kind, "files": count}
                for kind, count in sorted(by_kind.items(), key=lambda item: (-item[1], item[0]))
            ],
            "document_roles": [
                {"role": role, "files": count}
                for role, count in sorted(roles.items(), key=lambda item: (-item[1], item[0]))[:20]
            ],
            "source_layers": source_layers,
            "retrieval_routes": retrieval_routes,
            "source_graph": source_graph,
            "topic_map": topic_map,
            "section_map": section_map,
            "important_files": _important_files(cards),
            "file_cards": cards[:500],
            "known_gaps": _known_gaps(docs, by_layer),
            "updated_at": now,
        }
        memory.update(operator_guidance)
        conn.execute(
            """
            INSERT INTO dataset_memory(dataset_id, revision_id, schema, memory_json, reader_status, is_evidence, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(dataset_id) DO UPDATE SET
                revision_id=excluded.revision_id,
                schema=excluded.schema,
                memory_json=excluded.memory_json,
                reader_status=excluded.reader_status,
                is_evidence=0,
                updated_at=excluded.updated_at
            """,
            (dataset_id, revision_id, TYPED_MEMORY_SCHEMA, _json(memory), "bootstrap", now),
        )
        conn.commit()
        return memory


def _important_files(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority_weights = {
        "состав проекта": 100,
        "пояснительная записка": 95,
        "задание на проектирование": 90,
        "ведомость": 72,
        "спецификация": 70,
        "ГЭСН": 66,
        "ГЭСНм": 66,
        "ГЭСНп": 66,
        "ФЕР": 64,
        "ФСЭМ": 62,
        "ФСБЦ": 62,
        "сплит-форма/ФГИС": 60,
        "сметно-нормативная база": 58,
        "нормативный документ": 55,
        "чертёжный комплект": 50,
        "сметный расчёт": 40,
    }
    ranked = []
    for card in cards:
        role = str(card.get("document_role") or "")
        score = max((weight for term, weight in priority_weights.items() if term in role), default=0)
        score += min(4, int(card.get("chunk_count") or 0) // 250)
        score -= _service_noise_penalty(card)
        if score:
            ranked.append((score, "role_priority", card))
    if not ranked:
        for card in cards:
            if str(card.get("status") or "") != "INDEXED" and not int(card.get("chunk_count") or 0):
                continue
            score = min(40, int(card.get("chunk_count") or 0))
            if str(card.get("status") or "") == "INDEXED":
                score += 10
            score -= _service_noise_penalty(card)
            ranked.append((score, "indexed_chunk_rich", card))
    ranked.sort(key=lambda item: (-item[0], item[2].get("file_name", "")))
    return [
            {
                "file_name": card["file_name"],
                "document_role": card.get("document_role", ""),
                "content_layers": card.get("content_layers") or [],
                "navigation_terms": list(card.get("navigation_terms") or [])[:8],
                "summary": card.get("summary", ""),
                "chunk_count": int(card.get("chunk_count") or 0),
                "selection_reason": reason,
            }
        for _score, reason, card in ranked[:24]
    ]


def _ensure_memory_navigation(memory: dict[str, Any]) -> dict[str, Any]:
    if memory and not memory.get("important_files") and memory.get("file_cards"):
        memory["important_files"] = _important_files(list(memory.get("file_cards") or []))
    if memory and memory.get("file_cards"):
        cards = list(memory.get("file_cards") or [])
        for card in cards:
            if not card.get("navigation_terms"):
                card["navigation_terms"] = _navigation_terms_for_file(
                    str(card.get("file_name") or ""),
                    str(card.get("document_role") or ""),
                    [str(layer) for layer in (card.get("content_layers") or [])],
                    str((card.get("provenance") or {}).get("doc_type") or ""),
                    str((card.get("provenance") or {}).get("domain") or ""),
                )
        memory["file_cards"] = cards
        if not memory.get("source_layers"):
            counts: dict[str, int] = {}
            for card in cards:
                for layer in card.get("content_layers") or []:
                    counts[str(layer)] = counts.get(str(layer), 0) + 1
            memory["source_layers"] = _source_layers_from_counts(counts)
        if not memory.get("retrieval_routes"):
            memory["retrieval_routes"] = _retrieval_routes_for_dataset(cards, memory.get("source_layers") or [])
        if not memory.get("source_graph"):
            memory["source_graph"] = _source_graph_for_dataset(str(memory.get("dataset_id") or ""), cards, memory.get("source_layers") or [])
        if not memory.get("topic_map"):
            memory["topic_map"] = _build_topic_map(str(memory.get("dataset_id") or ""), cards, [])
        if not memory.get("section_map"):
            memory["section_map"] = _build_section_map(str(memory.get("dataset_id") or ""), [], cards)
    return memory


def _source_layers_from_counts(by_layer: dict[str, int]) -> list[dict[str, Any]]:
    layers = []
    for layer, count in sorted(by_layer.items(), key=lambda item: (-item[1], item[0])):
        role = SOURCE_LAYER_ROLES.get(layer, {})
        layers.append(
            {
                "id": layer,
                "label": CONTENT_LAYER_LABELS.get(layer, layer),
                "files": int(count),
                "role": role.get("role", "слой данных"),
                "use_for": role.get("use_for", "выбор источника и workflow"),
                "evidence_rule": role.get("evidence_rule", "подтверждать утверждения найденным источником"),
            }
        )
    return layers


def _retrieval_routes_for_dataset(cards: list[dict[str, Any]], source_layers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    available_layers = {str(layer.get("id") or "") for layer in source_layers}
    sorted_cards = sorted(
        cards,
        key=lambda card: (
            _service_noise_penalty(card),
            -int(card.get("chunk_count") or 0),
            str(card.get("file_name") or ""),
        ),
    )
    routes = []
    for template in RETRIEVAL_ROUTE_TEMPLATES:
        required = set(template.get("require_layers") or [])
        if required and not required.intersection(available_layers):
            continue
        layers = [layer for layer in template["prefer_layers"] if layer in available_layers]
        if not layers:
            continue
        target_files = []
        for card in sorted_cards:
            card_layers = {str(layer) for layer in (card.get("content_layers") or [])}
            role = str(card.get("document_role") or "")
            layer_hit = bool(card_layers.intersection(layers))
            role_hit = any(prefer in role for prefer in template["prefer_roles"])
            if layer_hit and (role_hit or len(target_files) < 6):
                target_files.append(
                    {
                        "file_name": card.get("file_name"),
                        "role": role,
                        "layers": list(card.get("content_layers") or []),
                        "navigation_terms": list(card.get("navigation_terms") or [])[:6],
                        "chunk_count": int(card.get("chunk_count") or 0),
                    }
                )
            if len(target_files) >= 10:
                break
        routes.append(
            {
                "id": template["id"],
                "when": template["when"],
                "prefer_layers": layers,
                "prefer_roles": template["prefer_roles"],
                "method": template["method"],
                "target_files": target_files,
                "is_decision": False,
            }
        )
    return routes


def _source_graph_for_dataset(dataset_id: str, cards: list[dict[str, Any]], source_layers: list[dict[str, Any]]) -> dict[str, Any]:
    edges: list[dict[str, Any]] = []
    top_files_by_layer: dict[str, list[dict[str, Any]]] = {}
    for layer in source_layers:
        layer_id = str(layer.get("id") or "")
        if not layer_id:
            continue
        edges.append(
            {
                "from": f"dataset:{dataset_id}",
                "to": f"layer:{layer_id}",
                "relation": "has_layer",
                "count": int(layer.get("files") or 0),
            }
        )
    by_role_layer: dict[tuple[str, str], int] = {}
    files_by_layer: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        role = str(card.get("document_role") or "документ")
        for layer in card.get("content_layers") or []:
            layer_id = str(layer)
            by_role_layer[(layer_id, role)] = by_role_layer.get((layer_id, role), 0) + 1
            files_by_layer.setdefault(layer_id, []).append(card)
    for (layer_id, role), count in sorted(by_role_layer.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))[:80]:
        edges.append(
            {
                "from": f"layer:{layer_id}",
                "to": f"role:{role}",
                "relation": "contains_role",
                "count": int(count),
            }
        )
    for layer_id, layer_cards in files_by_layer.items():
        layer_cards.sort(
            key=lambda card: (
                _service_noise_penalty(card),
                -int(card.get("chunk_count") or 0),
                str(card.get("file_name") or ""),
            )
        )
        top_files_by_layer[layer_id] = [
            {
                "file_name": card.get("file_name"),
                "role": card.get("document_role"),
                "navigation_terms": list(card.get("navigation_terms") or [])[:6],
                "chunk_count": int(card.get("chunk_count") or 0),
                "status": card.get("status"),
            }
            for card in layer_cards[:8]
        ]
    return {
        "schema": "dataset_source_graph_v1",
        "context_role": "navigation",
        "is_evidence": False,
        "dataset_id": dataset_id,
        "edges": edges,
        "top_files_by_layer": top_files_by_layer,
        "rule": "source_graph guides retrieval; final claims still require chunks/tables/graph/calculation trace",
    }


def _known_gaps(docs: list[dict[str, Any]], by_layer: dict[str, int]) -> list[str]:
    gaps: list[str] = []
    if not docs:
        gaps.append("В датасете нет документов в MetaDB.")
    pending = sum(1 for d in docs if str(d.get("status") or "") == "PENDING")
    errors = sum(1 for d in docs if str(d.get("status") or "") == "ERROR")
    if pending:
        gaps.append(f"{pending} файлов ещё ожидают индексации.")
    if errors:
        gaps.append(f"{errors} файлов с ошибкой индексации.")
    if not by_layer.get("tables"):
        gaps.append("Табличный слой не обнаружен; числовые сводки могут требовать чтения PDF/DOCX.")
    return gaps


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _reader_context(
    memory: dict[str, Any],
    *,
    file_limit: int | None = None,
    char_limit: int | None = None,
) -> str:
    if file_limit is None:
        file_limit = _env_int("LES_DATASET_READER_FILE_LIMIT", 240, minimum=20)
    if char_limit is None:
        char_limit = _env_int("LES_DATASET_READER_CONTEXT_CHARS", 64000, minimum=8000)
    important_names = {str(item.get("file_name") or "") for item in memory.get("important_files") or []}
    cards = list(memory.get("file_cards") or [])
    cards.sort(
        key=lambda card: (
            0 if str(card.get("file_name") or "") in important_names else 1,
            -int(card.get("chunk_count") or 0),
            str(card.get("file_name") or ""),
        )
    )
    payload = {
        "schema": "dataset_reader_input_v1",
        "dataset_id": memory.get("dataset_id"),
        "revision_id": memory.get("revision_id"),
        "document_count": memory.get("document_count", 0),
        "indexed_count": memory.get("indexed_count", 0),
        "chunk_count": memory.get("chunk_count", 0),
        "data_layers": memory.get("data_layers") or [],
        "file_kinds": memory.get("file_kinds") or [],
        "document_roles": memory.get("document_roles") or [],
        "important_files": memory.get("important_files") or [],
        "known_gaps": memory.get("known_gaps") or [],
        "file_cards_scope": {
            "included": min(len(cards), file_limit),
            "total": len(cards),
            "selection": (
                "important files first, then indexed/chunk-rich files; use as navigation, "
                "not as proof that omitted files do not exist"
            ),
        },
        "file_cards": [
            {
                "file_name": card.get("file_name"),
                "status": card.get("status"),
                "chunk_count": card.get("chunk_count", 0),
                "file_kind": card.get("file_kind"),
                "content_layers": card.get("content_layers") or [],
                "document_role": card.get("document_role"),
                "navigation_terms": list(card.get("navigation_terms") or [])[:8],
                "summary": card.get("summary"),
            }
            for card in cards[:file_limit]
        ],
        "retrieval_routes": memory.get("retrieval_routes") or [],
        "source_graph": memory.get("source_graph") or {},
        "topic_map": memory.get("topic_map") or {},
        "section_map": memory.get("section_map") or {},
    }
    text = _json(payload)
    if len(text) > char_limit:
        return text[:char_limit] + "\n...TRUNCATED..."
    return text


def _reader_instruction() -> str:
    return (
        "Ты reader-pass Л.Е.С.: изучаешь карту датасета и составляешь навигационную память. "
        "Это НЕ evidence и НЕ финальный ответ пользователю. Не выдумывай факты, которых нет во входе. "
        "Определи тип корпуса: проект, нормы, сметы, техничка, смешанный корпус или неизвестно. "
        "Укажи, какие файлы открывать для широких вопросов: паспорт объекта, состав проекта, ТЭП, "
        "инженерные разделы, сметы, спецификации, нормы. Если корпус похож на набор норм, не описывай его "
        "как строительный объект. Используй topic_map и section_map как оглавление: тема сначала ведёт "
        "к файлам и разделам, а не сразу к случайным чанкам. Выбери 10-30 конкретных file_roles из имён, которые есть во входе. "
        "Не добавляй в known_gaps фразу о том, что file_cards/file list ограничен или выбран частично: "
        "это нормальная навигационная выборка, а не отсутствие данных. Если для широкого вопроса файл "
        "виден в карте, советуй добрать его точечно, а не писать «данных нет». Верни только JSON по схеме."
    )


async def _run_reader_extraction(schema: dict[str, Any], instruction: str, context: str, *, max_attempts: int):
    from proxy.services.extract_service import run_structured_extraction

    return await run_structured_extraction(
        schema,
        instruction,
        context,
        max_attempts=max_attempts,
    )


def _store_reader_update(
    dataset_id: str,
    *,
    revision_id: str,
    status: str,
    updates: dict[str, Any],
    meta_db_path: str | None = None,
) -> dict[str, Any]:
    now = time.time()
    with _connect(meta_db_path) as conn:
        row = conn.execute(
            "SELECT memory_json FROM dataset_memory WHERE dataset_id=? AND revision_id=?",
            (dataset_id, revision_id),
        ).fetchone()
        memory = _loads(row["memory_json"], {}) if row else {}
        memory.update(updates)
        memory["reader_status"] = status
        memory["updated_at"] = now
        conn.execute(
            """
            UPDATE dataset_memory
            SET memory_json=?, reader_status=?, updated_at=?
            WHERE dataset_id=? AND revision_id=?
            """,
            (_json(memory), status, now, dataset_id, revision_id),
        )
        conn.commit()
        return memory


async def run_dataset_reader_pass(
    dataset_id: str,
    *,
    force: bool = False,
    meta_db_path: str | None = None,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Ask the active model to build a navigation map over typed memory.

    The result is stored as dataset memory, not evidence. Final answers must
    still retrieve chunks/tables/graph/calculations before asserting facts.
    """
    memory = await asyncio.to_thread(build_typed_dataset_memory, dataset_id, force=force, meta_db_path=meta_db_path)
    if memory.get("reader_status") == "model" and not force:
        return memory
    context = _reader_context(memory)
    result = await _run_reader_extraction(
        DATASET_READER_SCHEMA,
        _reader_instruction(),
        context,
        max_attempts=max_attempts,
    )
    revision_id = str(memory.get("revision_id") or "")
    if result.ok and isinstance(result.data, dict):
        return await asyncio.to_thread(
            _store_reader_update,
            dataset_id,
            revision_id=revision_id,
            status="model",
            updates={
                "reader_schema": DATASET_READER_SCHEMA_ID,
                "reader_output": result.data,
                "reader_errors": [],
                "reader_attempts": result.attempts,
                "reader_note": (
                    "Model reader output is navigation memory only. Evidence must be fetched from "
                    "chunks, tables, graph atoms or calculation services before final claims."
                ),
            },
            meta_db_path=meta_db_path,
        )
    return await asyncio.to_thread(
        _store_reader_update,
        dataset_id,
        revision_id=revision_id,
        status="model_failed",
        updates={
            "reader_schema": DATASET_READER_SCHEMA_ID,
            "reader_output": None,
            "reader_errors": list(result.errors or []),
            "reader_attempts": result.attempts,
        },
        meta_db_path=meta_db_path,
    )


def dataset_reader_after_parse_enabled() -> bool:
    return os.getenv("LES_DATASET_READER_AFTER_PARSE", "0").strip().lower() in {"1", "true", "yes", "on"}


def schedule_dataset_reader_pass(
    dataset_id: str,
    *,
    reason: str = "",
    force: bool = True,
    require_enabled: bool = True,
) -> dict[str, Any]:
    """Schedule a model reader pass on the current event loop, with per-process dedupe."""
    dataset_id = str(dataset_id)
    if require_enabled and not dataset_reader_after_parse_enabled():
        return {"scheduled": False, "reason": "disabled", "dataset_id": dataset_id}
    if dataset_id in _RUNNING_READER_TASKS:
        return {"scheduled": False, "reason": "already_running", "dataset_id": dataset_id}
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return {"scheduled": False, "reason": "no_event_loop", "dataset_id": dataset_id}

    _RUNNING_READER_TASKS.add(dataset_id)

    async def _runner() -> None:
        try:
            await run_dataset_reader_pass(dataset_id, force=force)
            logger.info("[dataset-reader] completed dataset=%s reason=%s", dataset_id, reason)
        except Exception:
            logger.exception("[dataset-reader] failed dataset=%s reason=%s", dataset_id, reason)
        finally:
            _RUNNING_READER_TASKS.discard(dataset_id)

    loop.create_task(_runner())
    return {"scheduled": True, "reason": reason or "manual", "dataset_id": dataset_id}


def get_typed_dataset_memory(dataset_id: str, *, meta_db_path: str | None = None) -> dict[str, Any]:
    with _connect(meta_db_path) as conn:
        row = conn.execute("SELECT memory_json FROM dataset_memory WHERE dataset_id=?", (dataset_id,)).fetchone()
        if row:
            memory = _ensure_memory_navigation(_loads(row["memory_json"], {}))
            if isinstance(memory, dict) and not memory.get("operator_guidance"):
                memory.update(_operator_guidance_from_profiles(conn, dataset_id))
            return memory
    return build_typed_dataset_memory(dataset_id, meta_db_path=meta_db_path)


def latest_file_cards(dataset_ids: list[str], *, meta_db_path: str | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    if not dataset_ids:
        return {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    with _connect(meta_db_path) as conn:
        qmarks = ",".join("?" * len(dataset_ids))
        rows = conn.execute(
            f"""
            SELECT fc.*
            FROM file_cards fc
            JOIN dataset_memory dm
              ON dm.dataset_id=fc.dataset_id AND dm.revision_id=fc.revision_id
            WHERE fc.dataset_id IN ({qmarks})
            """,
            [str(d) for d in dataset_ids],
        ).fetchall()
        for row in rows:
            card = dict(row)
            card["content_layers"] = _loads(card.pop("content_layers_json", "[]"), [])
            card["key_entities"] = _loads(card.pop("key_entities_json", "[]"), [])
            card["provenance"] = _loads(card.pop("provenance_json", "{}"), {})
            out[(str(card.get("dataset_id") or ""), str(card.get("file_name") or ""))] = card
    return out


def current_dataset_revision_id(dataset_id: str, *, meta_db_path: str | None = None) -> str:
    try:
        with _connect(meta_db_path) as conn:
            row = conn.execute(
                "SELECT revision_id FROM dataset_memory WHERE dataset_id=?",
                (str(dataset_id),),
            ).fetchone()
            return str(row["revision_id"] or "") if row else ""
    except Exception:
        return ""


def typed_memory_prompt_block(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return ""
    lines = [
        "КАРТА ДАТАСЕТА ЛЕС (навигация, не evidence):",
        "Используй эту карту, чтобы выбирать файлы/слои/инструменты. "
        "Факты и числа подтверждай источниками, таблицами, графом или расчётным кодом.",
    ]
    for memory in memories:
        if not memory:
            continue
        lines.append(
            f"\nДатасет {memory.get('dataset_id')}: "
            f"{memory.get('document_count', 0)} файлов, {memory.get('chunk_count', 0)} чанков."
        )
        layers = memory.get("data_layers") or []
        if layers:
            lines.append(
                "Слои: "
                + ", ".join(f"{x.get('label') or x.get('id')}×{x.get('files')}" for x in layers[:10])
            )
        important = memory.get("important_files") or []
        if important:
            lines.append("Ключевые файлы для широких вопросов:")
            for item in important[:12]:
                lines.append(f"- {item.get('file_name')} — {item.get('document_role')}")
        topic_map = memory.get("topic_map") if isinstance(memory.get("topic_map"), dict) else {}
        topics = topic_map.get("topics") if isinstance(topic_map, dict) else []
        if topics:
            lines.append("Карта тем:")
            for topic in list(topics)[:8]:
                files = _brief_join(
                    [str(f.get("file_name") or "") for f in (topic.get("top_files") or [])],
                    limit=3,
                )
                sections = _brief_join(
                    [str(s.get("heading") or "") for s in (topic.get("top_sections") or [])],
                    limit=2,
                )
                tail = "; ".join(part for part in [f"файлы: {files}" if files else "", f"разделы: {sections}" if sections else ""] if part)
                lines.append(f"- {topic.get('label') or topic.get('id')}: {tail}")
        reader = memory.get("reader_output") if memory.get("reader_status") == "model" else None
        if isinstance(reader, dict):
            summary = str(reader.get("reader_summary") or "").strip()
            if summary:
                lines.append(f"Reader-pass: {summary[:700]}")
            where = reader.get("where_to_look") or []
            if where:
                lines.append("Reader-pass советует искать:")
                for item in where[:8]:
                    files = ", ".join(str(f) for f in (item.get("target_files") or [])[:5])
                    lines.append(f"- {item.get('question_type')}: {files} — {item.get('reason')}")
        gaps = memory.get("known_gaps") or []
        if gaps:
            lines.append("Ограничения карты: " + "; ".join(str(g) for g in gaps[:4]))
    return "\n".join(lines)


def _brief_join(items: list[str], *, limit: int = 8) -> str:
    values = [str(item or "").strip() for item in items if str(item or "").strip()]
    return ", ".join(values[:limit])


def _file_card_by_name(memory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(card.get("file_name") or ""): card
        for card in (memory.get("file_cards") or [])
        if str(card.get("file_name") or "")
    }


def _task_guidance(question: str) -> list[str]:
    q = (question or "").casefold().replace("ё", "е")
    guidance = []
    if re.search(r"(смет|стоимост|вор\b|лср|гэсн|рим|расцен|цена)", q):
        guidance.append(
            "Для сметы сначала найди ВОР/спецификации/ЛСР/таблицы объёмов, затем добирай нормы и цены; "
            "brief не заменяет строки источников и расчёт."
        )
    if re.search(r"(нормоконтрол|замечан|провер|гост|сп\s*\d|снип|требован)", q):
        guidance.append(
            "Для нормативного вопроса сначала выбери документ-кандидат, затем пункт/таблицу/приложение, "
            "и только потом формулируй вывод."
        )
    if re.search(r"(расскажи|обзор|изучи|проект|объект|корпус|датасет|документац)", q):
        guidance.append(
            "Для широкого обзора открой паспортные документы, состав проекта и пояснительные записки; "
            "таблицы и чертежи используй как уточняющий слой."
        )
    if re.search(r"(таблиц|спецификац|ведомост|перечен|реестр|список)", q):
        guidance.append(
            "Для табличных вопросов ищи файлы со слоями tables/calculations и подтверждай числа строками таблиц."
        )
    return guidance


def _normative_navigation_lines(memory: dict[str, Any], question: str, *, max_files: int = 24) -> list[str]:
    q = (question or "").casefold().replace("ё", "е")
    if not re.search(r"(норм|требован|гост|сп\s*\d|снип|пуэ|пункт|раздел|допускается|предусматрив|обязател|нужно|следует)", q):
        return []
    try:
        from proxy.services.kot_service import extract_norm_refs

        norm_refs = [str(ref).casefold().replace(" ", "") for ref in extract_norm_refs(question)]
    except Exception:  # noqa: BLE001
        norm_refs = []

    candidates: list[tuple[int, dict[str, Any]]] = []
    for card in memory.get("file_cards") or []:
        layers = {str(layer) for layer in (card.get("content_layers") or [])}
        file_kind = str(card.get("file_kind") or "")
        role = str(card.get("document_role") or "").casefold()
        file_name = str(card.get("file_name") or "")
        low_name = file_name.casefold().replace(" ", "")
        if "normative" not in layers and file_kind != "normative" and "норматив" not in role:
            continue
        score = 10 + min(10, int(card.get("chunk_count") or 0) // 40)
        if norm_refs and any(ref in low_name for ref in norm_refs):
            score += 100
        if str(card.get("status") or "") == "INDEXED":
            score += 5
        score -= _service_noise_penalty(card)
        candidates.append((score, card))
    if not candidates:
        return []

    candidates.sort(key=lambda item: (-item[0], str(item[1].get("file_name") or "")))
    lines = [
        "Нормативная навигация:",
        "- Сначала выбери нормативный документ-кандидат по предмету вопроса; затем ищи внутри него пункт, подпункт, таблицу или приложение; затем формулируй вывод.",
        "- Если вопрос содержит развилку «требуется / не требуется», ищи обе стороны нормы. Если одна сторона не найдена в открытых фрагментах, не додумывай её.",
        "- Список ниже не доказательство и не полный реестр; это карта, какие файлы открыть через retrieval/doc_filter.",
    ]
    for _score, card in candidates[:max_files]:
        chunks = int(card.get("chunk_count") or 0)
        status = str(card.get("status") or "")
        terms = _brief_join([str(term) for term in (card.get("navigation_terms") or [])], limit=6)
        terms_tail = f"; искать как: {terms}" if terms else ""
        lines.append(
            f"- {card.get('file_name')} — {card.get('document_role') or 'нормативный документ'}; "
            f"status {status}; чанков {chunks}{terms_tail}"
        )
    return lines


def dataset_brief_for_model(
    memories: list[dict[str, Any]],
    *,
    question: str = "",
    max_files: int = 14,
    max_chars: int = 7000,
) -> str:
    """Compact model-facing brief over dataset memory.

    The brief is deliberately model-first: it helps the model decide what to
    read next, but it is not evidence and does not choose conclusions.
    """
    clean_memories = [memory for memory in memories if memory]
    if not clean_memories:
        return ""
    lines = [
        "ПАСПОРТ ОБЛАСТИ ДЛЯ МОДЕЛИ (навигация, не источник фактов)",
        f"schema: {DATASET_BRIEF_SCHEMA_ID}",
        "Главное: модель и текущий промпт принимают профессиональное решение. "
        "Этот brief только помогает понять корпус и выбрать файлы. "
        "Факты, числа и выводы бери из найденных фрагментов документов, таблиц, графа или расчётной трассы.",
        "Не пересказывай пользователю этот brief, его schema и служебные названия; в видимом ответе говори как инженер.",
        "Связь с фрагментами: file_name из этого brief совпадает с doc_name/file_name в Qdrant и lexical_chunks; "
        "для проверки открывай конкретный файл через retrieval/doc_filter и ссылайся уже на найденный фрагмент.",
    ]
    task_guidance = _task_guidance(question)
    if task_guidance:
        lines.append("Маршрут под текущий вопрос:")
        lines.extend(f"- {item}" for item in task_guidance[:4])
    for memory in clean_memories:
        memory = _ensure_memory_navigation(memory)
        dataset_id = str(memory.get("dataset_id") or "")
        lines.append(
            f"\nОбласть {dataset_id}: файлов {memory.get('document_count', 0)}, "
            f"проиндексировано {memory.get('indexed_count', 0)}, чанков {memory.get('chunk_count', 0)}."
        )
        guidance = str(memory.get("operator_guidance") or "").strip()
        if guidance:
            lines.append(
                "Комментарий оператора для модели: "
                + guidance[:900]
                + " (это навигация/пояснение к чтению корпуса, не evidence для фактов)."
            )
        layers = memory.get("data_layers") or []
        if layers:
            lines.append(
                "Слои данных: "
                + ", ".join(f"{x.get('label') or x.get('id')} ({x.get('files')})" for x in layers[:10])
            )
        source_layers = memory.get("source_layers") or []
        if source_layers:
            lines.append("Что означают слои:")
            for layer in source_layers[:8]:
                lines.append(
                    f"- {layer.get('label') or layer.get('id')}: {layer.get('use_for')}; "
                    f"проверка: {layer.get('evidence_rule')}"
                )
        roles = memory.get("document_roles") or []
        if roles:
            lines.append(
                "Роли документов: "
                + ", ".join(f"{x.get('role')} ({x.get('files')})" for x in roles[:10])
            )
        routes = memory.get("retrieval_routes") or []
        if routes:
            lines.append("Маршруты поиска по типам вопросов:")
            for route in routes[:6]:
                files = _brief_join([str(f.get("file_name") or "") for f in (route.get("target_files") or [])], limit=4)
                tail = f"; первые файлы: {files}" if files else ""
                lines.append(f"- {route.get('when')}: {route.get('method')}{tail}")
        source_graph = memory.get("source_graph") or {}
        graph_files = source_graph.get("top_files_by_layer") if isinstance(source_graph, dict) else {}
        if isinstance(graph_files, dict) and graph_files:
            lines.append("Связка слои -> файлы:")
            for layer_id, files in list(graph_files.items())[:6]:
                names = _brief_join([str(f.get("file_name") or "") for f in list(files)[:4]], limit=4)
                if names:
                    lines.append(f"- {CONTENT_LAYER_LABELS.get(layer_id, layer_id)}: {names}")
        topic_map = memory.get("topic_map") if isinstance(memory.get("topic_map"), dict) else {}
        topics = topic_map.get("topics") if isinstance(topic_map, dict) else []
        if topics:
            lines.append("Карта тем датасета:")
            for topic in list(topics)[:8]:
                files = _brief_join(
                    [str(f.get("file_name") or "") for f in (topic.get("top_files") or [])],
                    limit=4,
                )
                sections = _brief_join(
                    [str(s.get("heading") or "") for s in (topic.get("top_sections") or [])],
                    limit=3,
                )
                aliases = _brief_join([str(a) for a in (topic.get("query_aliases") or [])], limit=5)
                tail_parts = []
                if files:
                    tail_parts.append(f"первые файлы: {files}")
                if sections:
                    tail_parts.append(f"разделы: {sections}")
                if aliases:
                    tail_parts.append(f"искать как: {aliases}")
                tail = "; ".join(tail_parts)
                lines.append(f"- {topic.get('label') or topic.get('id')}: {tail}")
        section_map = memory.get("section_map") if isinstance(memory.get("section_map"), dict) else {}
        section_files = section_map.get("files") if isinstance(section_map, dict) else []
        if section_files:
            lines.append("Оглавление/разделы, уже видимые в индексе:")
            for item in list(section_files)[:6]:
                headings = _brief_join([str(s.get("heading") or "") for s in (item.get("sections") or [])], limit=4)
                if headings:
                    lines.append(f"- {item.get('file_name')}: {headings}")
        norm_lines = _normative_navigation_lines(memory, question)
        if norm_lines:
            lines.extend(norm_lines)
        cards_by_name = _file_card_by_name(memory)
        important = memory.get("important_files") or []
        if important:
            lines.append("Открывать в первую очередь:")
            for item in important[:max_files]:
                file_name = str(item.get("file_name") or "")
                card = cards_by_name.get(file_name, {})
                chunks = card.get("chunk_count")
                layers_text = _brief_join(list(item.get("content_layers") or card.get("content_layers") or []), limit=4)
                suffix = f"; чанков {chunks}" if chunks is not None else ""
                if layers_text:
                    suffix += f"; слои {layers_text}"
                terms = _brief_join([str(term) for term in (item.get("navigation_terms") or card.get("navigation_terms") or [])], limit=6)
                if terms:
                    suffix += f"; искать как {terms}"
                lines.append(f"- {file_name} — {item.get('document_role') or card.get('document_role') or 'документ'}{suffix}")
        reader = memory.get("reader_output") if memory.get("reader_status") == "model" else None
        if isinstance(reader, dict):
            summary = str(reader.get("reader_summary") or "").strip()
            if summary:
                lines.append(f"Reader-pass модели: {summary[:700]}")
            where = reader.get("where_to_look") or []
            if where:
                lines.append("Куда смотреть по типам вопросов:")
                for item in where[:8]:
                    files = _brief_join([str(f) for f in (item.get("target_files") or [])], limit=5)
                    lines.append(f"- {item.get('question_type')}: {files} — {item.get('reason')}")
            answer_guidance = str(reader.get("answer_guidance") or "").strip()
            if answer_guidance:
                lines.append(f"Подсказка reader-pass: {answer_guidance[:500]}")
        gaps = [str(g) for g in (memory.get("known_gaps") or []) if str(g).strip()]
        if gaps:
            lines.append("Известные ограничения карты: " + "; ".join(gaps[:5]))
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[:max_chars].rsplit("\n", 1)[0].rstrip() + "\n...BRIEF_TRUNCATED..."
    return text
