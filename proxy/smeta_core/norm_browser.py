"""Universal model-visible norm browser over the typed machine base.

It retrieves exact/full-code or lexical cards. It never returns a selected norm and
contains no object-specific boosts, family guesses or applicability decisions.
"""

from __future__ import annotations
from backend.http_client_policy import trust_env_for_url

import asyncio
import json
import logging
import os
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models

from backend.inference.bm25_sparse import SPARSE_VECTOR_NAME, encode_bm25
from backend.qdrant_adapter import EmbedClient
from backend.rag_config import prepare_query_for_embedding
from backend.reranker import select_reranker_cls

from proxy.services.smeta_norm_store import SmetaNormRow, get_smeta_norm_store
from proxy.smeta_core.norm_revision import NormRevisionConflict
from proxy.smeta_core.integrity import normative_base_integrity


logger = logging.getLogger("les.smeta.norm_browser")


_FULL_CODE_RE = re.compile(
    r"((?:ГЭСНМР|ГЭСНМ|ГЭСНП|ГЭСНР|ГЭСН|ФЕРМР|ФЕРМ|ФЕРП|ФЕРР|ФЕР|ТЕРМР|ТЕРМ|ТЕРП|ТЕРР|ТЕР)"
    r"\s*:?\s*(\d{2}-\d{2}-\d{3}-\d{2}))",
    re.IGNORECASE,
)

_RUSSIAN_SUFFIXES = tuple(sorted({
    "иями", "ями", "ами", "ого", "ему", "ому", "ыми", "ими", "ение", "ания",
    "ения", "ование", "ировать", "ировка", "ический", "ическая", "ические",
    "ость", "ости", "овка", "евка", "ками", "ями", "ами", "ами", "ого",
    "ая", "яя", "ое", "ее", "ые", "ие", "ый", "ий", "ой", "ов", "ев",
    "ам", "ям", "ах", "ях", "ка", "ки", "ку", "я", "а", "ы", "и", "у",
}, key=len, reverse=True))

_CATALOG_COMPASS_STOP_WORDS = frozenset({
    "для", "или", "при", "это", "что", "как", "под", "над", "без", "все",
    "работ", "работы", "монтаж", "установка", "установки", "сборник",
    "официальный", "типичный", "типовые", "оборудование",
})


def _base_path() -> Path:
    from proxy.smeta_core.base_registry import active_base

    return Path(active_base()["base_path"])


def _connect_base_readonly(base_path: Path) -> sqlite3.Connection:
    """Open a consistent revision-checked transaction without source writes."""
    from proxy.smeta_core.base_registry import runtime_data_path
    from proxy.smeta_core.norm_revision import readonly_revision_connection

    resolved = runtime_data_path(base_path)
    try:
        return readonly_revision_connection(resolved)
    except sqlite3.OperationalError as error:
        raise sqlite3.OperationalError(
            f"unable to open normative database {resolved}: {error}"
        ) from error


def _norm_key(value: str) -> str:
    match = _FULL_CODE_RE.search(str(value or ""))
    if not match:
        return ""
    full = re.sub(r"\s+", "", match.group(1)).replace(":", "")
    bare = match.group(2)
    family = full[: -len(bare)]
    family = "ГЭСН" + family[4:].lower() if family.upper().startswith("ГЭСН") else family
    family = "ФЕР" + family[3:].lower() if family.upper().startswith("ФЕР") else family
    family = "ТЕР" + family[3:].lower() if family.upper().startswith("ТЕР") else family
    return f"{family}:{bare}"


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


@lru_cache(maxsize=1)
def _normative_catalog_metadata() -> dict[str, Any]:
    """Load model-visible base taxonomy; it explains scope but never selects it."""
    path = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "domain"
        / "smeta_normative_catalog.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _plain_source_text(value: Any) -> str:
    text = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.replace("&nbsp;", " ").split())


def _source_lines(value: Any) -> list[str]:
    text = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return [
        " ".join(line.replace("&nbsp;", " ").split()).strip()
        for line in text.splitlines()
        if " ".join(line.replace("&nbsp;", " ").split()).strip()
    ]


def _collection_title(source_doc: Any, collection: str) -> str:
    """Extract the official collection heading from typed provenance."""
    text = _plain_source_text(source_doc)
    collection_number = str(int(collection)) if collection.isdigit() else collection
    pattern = re.compile(
        rf"(?:Государственные [^.]+?\.\s*)?Сборник\s+0*{re.escape(collection_number)}\.\s*"
        r"(.+?)(?=\s+(?:Сборник|Отдел|Раздел|Подраздел|Таблица)\s+|\Z)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    return " ".join(match.group(1).split()).strip(" .") if match else ""


def _family_catalog_item(row: sqlite3.Row) -> dict[str, Any]:
    family = str(row["key"] or "")
    metadata = (
        (_normative_catalog_metadata().get("families") or {}).get(family)
        if family
        else None
    )
    item = dict(row)
    if isinstance(metadata, dict):
        item.update({
            "official_name": str(metadata.get("official_name") or ""),
            "purpose": str(metadata.get("purpose") or ""),
            "typical_scope": [
                str(value)
                for value in (metadata.get("typical_scope") or [])
                if str(value).strip()
            ],
            "not_for": [
                str(value)
                for value in (metadata.get("not_for") or [])
                if str(value).strip()
            ],
            "questions_to_ask": [
                str(value)
                for value in (metadata.get("questions_to_ask") or [])
                if str(value).strip()
            ],
            "navigation_url": str(metadata.get("navigation_url") or ""),
            "approval_basis": str(metadata.get("approval_basis") or ""),
            "calculation_use": str(metadata.get("calculation_use") or ""),
            "source_ref": str(metadata.get("source_ref") or ""),
        })
    item.update({
        "node_id": f"catalog:family:{family}",
        "parent_id": "catalog:root",
        "node_type": "family",
        "cipher": family,
        "edition": "ФСНБ-2022",
    })
    return item


def _collection_catalog_item(row: sqlite3.Row, *, family: str) -> dict[str, Any]:
    item = dict(row)
    key = str(row["key"] or "")
    title = _collection_title(row["source_example"], key)
    item.update({
        "node_id": f"catalog:collection:{family}:{key}",
        "parent_id": f"catalog:family:{family}",
        "node_type": "collection",
        "cipher": key,
        "edition": "ФСНБ-2022",
        "title": title,
        "purpose": (
            f"Официальный сборник {family} {key}: {title}"
            if title
            else f"Официальный сборник {family} {key}"
        ),
        "typical_scope": [title] if title else [],
        "source_ref": (
            f"ФСНБ-2022 · {family}, сборник {key}"
            + (f" «{title}»" if title else "")
        ),
    })
    return item


def _collection_passport(
    conn: sqlite3.Connection,
    *,
    family: str,
    collection: str,
) -> dict[str, Any]:
    """Build one bounded navigation passport from the active typed edition."""
    rows = conn.execute(
        """
        SELECT bare_code, norm_name, norm_unit, source_doc
        FROM norms
        WHERE base_type=? AND substr(bare_code,1,2)=?
        ORDER BY bare_code
        LIMIT 48
        """,
        (family, collection),
    ).fetchall()
    if not rows:
        return {}
    title = _collection_title(rows[0]["source_doc"], collection)
    sections: list[str] = []
    table_examples: list[str] = []
    units: list[str] = []
    for row in rows:
        unit = " ".join(str(row["norm_unit"] or "").split()).strip()
        if unit and unit not in units:
            units.append(unit)
        for line in _source_lines(row["source_doc"]):
            if re.match(r"^(?:Отдел|Раздел|Подраздел)\s+", line, re.IGNORECASE):
                if line not in sections:
                    sections.append(line)
            if line.casefold().startswith("таблица ") and line not in table_examples:
                table_examples.append(line)
    family_meta = (
        (_normative_catalog_metadata().get("families") or {}).get(family)
        or {}
    )
    return {
        "schema": "smeta_norm_collection_passport_v1",
        "family": family,
        "collection": collection,
        "title": title,
        "purpose": (
            f"Навигация по официальному сборнику {family} {collection}"
            + (f" «{title}»" if title else "")
        ),
        "representative_sections": sections[:6],
        "representative_tables": table_examples[:4],
        "representative_units": units[:8],
        "family_exclusions": [
            str(value)
            for value in (family_meta.get("not_for") or [])
            if str(value).strip()
        ][:4],
        "scope_questions": [
            str(value)
            for value in (family_meta.get("questions_to_ask") or [])
            if str(value).strip()
        ][:4],
        "source_ref": (
            f"ФСНБ-2022 · {family}, сборник {collection}"
            + (f" «{title}»" if title else "")
        ),
        "passport_role": "navigation_only",
        "requires_scoped_search": True,
        "requires_full_norm_read": True,
    }


def _catalog_heading(source_doc: Any, *prefixes: str) -> str:
    """Return the first official hierarchy heading with one of the prefixes."""
    normalized = tuple(prefix.casefold() for prefix in prefixes)
    for line in _source_lines(source_doc):
        if line.casefold().startswith(normalized):
            return line
    return ""


def _section_code(value: Any, *, collection: str = "") -> str:
    """Normalize the encoded FSNB child below a collection (for example 10-04)."""
    digits = re.sub(r"\D", "", str(value or ""))[:4]
    if len(digits) == 2 and collection:
        digits = f"{collection}{digits}"
    if len(digits) != 4:
        return ""
    return f"{digits[:2]}-{digits[2:]}"


def _section_catalog_item(row: sqlite3.Row, *, family: str) -> dict[str, Any]:
    item = dict(row)
    key = str(row["key"] or "")
    official_heading = _catalog_heading(row["source_example"], "Отдел ", "Раздел ")
    title = re.sub(
        r"^(?:Отдел|Раздел)\s+\d+[.]?\s*",
        "",
        official_heading,
        flags=re.IGNORECASE,
    ).strip()
    item.update({
        "node_id": f"catalog:section:{family}:{key}",
        "parent_id": f"catalog:collection:{family}:{key[:2]}",
        "node_type": "section",
        "cipher": key,
        "edition": "ФСНБ-2022",
        "section_code": key,
        "navigation_kind": "section",
        "official_heading": official_heading,
        "title": title or official_heading or key,
        "purpose": official_heading or f"Официальный раздел {family} {key}",
        "source_ref": (
            f"ФСНБ-2022 · {family}, раздел каталога {key}"
            + (f" «{title}»" if title else "")
        ),
    })
    return item


def _table_catalog_item(row: sqlite3.Row, *, family: str) -> dict[str, Any]:
    item = dict(row)
    key = str(row["key"] or "")
    table_heading = _catalog_heading(row["source_example"], "Таблица ")
    title = re.sub(
        rf"^Таблица\s+(?:{re.escape(family)}\s*)?{re.escape(key)}\s*",
        "",
        table_heading,
        flags=re.IGNORECASE,
    ).strip()
    hierarchy = [
        line
        for line in _source_lines(row["source_example"])
        if re.match(r"^(?:Отдел|Раздел|Подраздел)\s+", line, re.IGNORECASE)
    ]
    norm_name_examples = [
        " ".join(value.split())
        for value in str(row["norm_names"] or "").split("\x1f")
        if " ".join(value.split())
    ][:16]
    item.update({
        "node_id": f"catalog:table:{family}:{key}",
        "parent_id": f"catalog:section:{family}:{key[:5]}",
        "node_type": "table",
        "cipher": key,
        "edition": "ФСНБ-2022",
        "table_code": key,
        "navigation_kind": "table",
        "official_heading": table_heading,
        "title": title or table_heading or key,
        "purpose": table_heading or f"Официальная таблица {family} {key}",
        "hierarchy": hierarchy,
        "norm_name_examples": norm_name_examples,
        "source_ref": (
            f"ФСНБ-2022 · {family}, таблица {key}"
            + (f" «{title}»" if title else "")
        ),
    })
    return item


def _card(
    conn: sqlite3.Connection, row: sqlite3.Row, *, full_resources: bool = False,
) -> dict[str, Any]:
    resource_columns = {str(item[1]) for item in conn.execute('PRAGMA table_info(resources)')}
    price_column = 'price' if 'price' in resource_columns else 'NULL AS price'
    # A resource can originate from a different publication than its parent.
    # Preserve stored provenance; older schemas mean unknown, never inheritance.
    source_columns = ', '.join(
        name if name in resource_columns else f'NULL AS {name}'
        for name in ('source_doc', 'source_guid')
    )
    resources = conn.execute(
        """
        SELECT kind, count(*) AS count
        FROM resources WHERE parent_norm_id = ? GROUP BY kind ORDER BY kind
        """,
        (row["norm_id"],),
    ).fetchall()
    preview = conn.execute(
        f"""
        SELECT rowid AS row_id, kind, resource_code, resource_name, resource_unit, per_unit, {price_column}, {source_columns}
        FROM resources
        WHERE parent_norm_id = ? AND trim(coalesce(resource_name, '')) <> ''
        ORDER BY CASE kind WHEN 'machine' THEN 0 WHEN 'material' THEN 1 ELSE 2 END,
                 resource_code, resource_name
        LIMIT 16
        """,
        (row["norm_id"],),
    ).fetchall()
    card = {
        "norm_id": row["norm_id"],
        "norm_code": row["display_code"],
        "norm_key": row["norm_key"],
        "edition": row["edition"],
        "base_type": row["base_type"],
        "title": row["norm_name"],
        "table_heading": _catalog_heading(row['source_doc'], 'Таблица '),
        "measure_unit": row["norm_unit"],
        "work_steps": _json_list(row["work_steps"]),
        "resource_count": int(row["resource_count"]),
        "resource_kinds": {str(item["kind"]): int(item["count"]) for item in resources},
        # Names are diagnostic evidence for technology mismatch (cranes, welding,
        # nuclear-only machinery, etc.), not an independent reason to bind a norm.
        "resource_preview": [
            {
                "kind": str(item["kind"] or ""),
                "code": str(item["resource_code"] or ""),
                "name": str(item["resource_name"] or ""),
                "unit": str(item["resource_unit"] or ""),
                "per_unit": item["per_unit"],
                "price": item["price"],
                "source_doc": item["source_doc"],
                "source_guid": item["source_guid"],
                "row_id": item["row_id"],
                "source_resource_ids": [str(item["row_id"])],
            }
            for item in preview
        ],
        "source_ref": f"{row['source_doc']}#guid={row['source_guid']}",
    }
    from proxy.smeta_core.norm_revision import identity_for_row
    card['normative_identity'] = identity_for_row(row, conn.base_sha256)
    if full_resources:
        # Exact model-authored code reads the source rows, including labor,
        # unnamed rows and repeated codes. Preview order/limits stay separate.
        rows = conn.execute(
            "SELECT rowid AS row_id, kind, resource_code, resource_name, "
            f"resource_unit, per_unit, {price_column}, {source_columns} FROM resources "
            "WHERE parent_norm_id = ? ORDER BY rowid",
            (row["norm_id"],),
        ).fetchall()
        card["resources"] = [
            {"row_id": item["row_id"], "kind": str(item["kind"] or ""),
             "code": str(item["resource_code"] or ""),
             "name": str(item["resource_name"] or ""),
             "unit": str(item["resource_unit"] or ""), "per_unit": item["per_unit"],
             "price": item['price'], "source_resource_ids": [str(item['row_id'])],
             "source_doc": item['source_doc'], "source_guid": item['source_guid']}
            for item in rows
        ]
        card["resources_complete"] = len(rows) == int(row["resource_count"])
        from proxy.smeta_core.resource_identity import normalise_resource, dedupe_resources
        calculated, _ = dedupe_resources([normalise_resource(dict(item)) for item in rows], normative_identity=card['normative_identity'])
        card['resource_groups'] = [item for item in calculated if item.get('source_resource_group_id')]
        membership = {source_id: group['source_resource_group_id'] for group in card['resource_groups']
            for source_id in group['source_resource_ids']}
        for item in card['resources']:
            if str(item['row_id']) in membership:
                item['source_resource_group_id'] = membership[str(item['row_id'])]
    return card


def _cards_by_norm_keys(norm_keys: list[str], *, base_path: Path,
                        connection: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    ordered = [str(key) for key in norm_keys if str(key)]
    if not ordered or not base_path.exists():
        return []
    conn = connection if connection is not None else _connect_base_readonly(base_path)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in ordered)
        rows = conn.execute(
            f"SELECT * FROM norms WHERE norm_key IN ({placeholders})",
            ordered,
        ).fetchall()
        by_key = {str(row["norm_key"]): _card(conn, row) for row in rows}
        return [by_key[key] for key in ordered if key in by_key]
    finally:
        if connection is None:
            conn.close()


def _rag_collection() -> str:
    from proxy.smeta_core.base_registry import active_base

    return os.getenv("LES_SMETA_NORM_RAG_COLLECTION", "").strip() or str(active_base().get("rag_collection") or "")


def _rag_embedding_model() -> str:
    from proxy.smeta_core.base_registry import active_base

    return (
        os.getenv("LES_SMETA_NORM_EMBED_MODEL", "").strip()
        or str(active_base().get("rag_embedding_model") or "qwen3-embedding-0.6b")
    )


@lru_cache(maxsize=1)
def _retrieval_vocabulary() -> tuple[dict[str, Any], ...]:
    path = Path(__file__).resolve().parents[2] / "config" / "domain" / "smeta_retrieval_vocabulary.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    rules = payload.get("rules") if isinstance(payload, dict) else []
    return tuple(rule for rule in (rules or []) if isinstance(rule, dict))


def _query_variants(query: str, *, stage: str = "norm") -> list[str]:
    """Expose documented user-language → normative-language search variants."""
    original = " ".join(str(query or "").split()).strip()
    if not original:
        return []
    low = original.casefold().replace("ё", "е")
    expansions_found: list[str] = []
    for rule in _retrieval_vocabulary():
        stages = {
            str(value or "").strip().casefold()
            for value in (rule.get("stages") or [])
            if str(value or "").strip()
        }
        if stages and str(stage or "").strip().casefold() not in stages:
            continue
        triggers = [str(value or "").casefold().replace("ё", "е") for value in rule.get("match_any") or []]
        expansions = [rule.get("query")] if rule.get("query") else list(rule.get("queries") or [])
        if any(trigger and trigger in low for trigger in triggers):
            expansions_found.extend(
                expansion
                for value in expansions
                if (expansion := " ".join(str(value or "").split()).strip())
            )
    # Normative-language variants lead retrieval; the untouched user query is
    # retained as the final recall channel and remains visible in trace.
    return list(dict.fromkeys([*expansions_found, original]))


def _catalog_compass_roots(value: object) -> set[str]:
    """Normalize official catalog identity without adding a selected cipher."""
    roots = set()
    for token in re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", str(value or "").casefold()):
        normalized = token.replace("ё", "е")
        if len(normalized) < 4 or normalized in _CATALOG_COMPASS_STOP_WORDS:
            continue
        roots.add(normalized[:7] if len(normalized) > 7 else normalized)
    return roots


_UNIT_DIMENSIONS: dict[str, str] = {
    "т": "weight",
    "кг": "weight",
    "тонн": "weight",
    "тонна": "weight",
    "м": "linear",
    "п.м": "linear",
    "мп": "linear",
    "пог.м": "linear",
    "погонный метр": "linear",
    "км": "linear",
    "м2": "area",
    "м²": "area",
    "100 м2": "area",
    "100 м²": "area",
    "м3": "volume",
    "м³": "volume",
    "100 м3": "volume",
    "100 м³": "volume",
    "шт": "piece",
    "компл": "piece",
    "комплект": "piece",
    "ед": "piece",
    "порт": "piece",
    "точка": "piece",
}

_DIMENSION_INCOMPATIBLE_WORDS: dict[str, tuple[str, ...]] = {
    "weight": ("деревян", "кирпич", "гипсокартон", "градирни"),
    "linear": ("кирпич", "монолитные бетонные", "градирни"),
    "area": ("градирни",),
    "volume": ("оборудование связи", "приборы", "автоматизированные системы"),
}


def catalog_compass_score(query: str, item: dict[str, Any]) -> float:
    """Score overlap with official node text; navigation only, never selection."""
    query_roots = _catalog_compass_roots(query)
    catalog_roots = _catalog_compass_roots(
        " ".join([
            str(item.get("title") or ""),
            str(item.get("purpose") or ""),
            " ".join(str(value) for value in (item.get("typical_scope") or [])),
        ])
    )
    if not query_roots or not catalog_roots:
        return 0.0
    overlap = query_roots & catalog_roots
    if not overlap:
        return 0.0
    catalog_coverage = len(overlap) / len(catalog_roots)
    query_coverage = len(overlap) / len(query_roots)
    score = (2.0 * catalog_coverage) + query_coverage

    q_lower = f" {query.casefold()} "
    item_text = " ".join([
        str(item.get("title") or ""),
        str(item.get("purpose") or ""),
        " ".join(str(v) for v in (item.get("typical_scope") or [])),
    ]).casefold()

    # Material contradiction check: only penalize if work explicitly specifies ONE material and node is another
    is_explicitly_wooden = any(w in q_lower for w in ("деревян", "брус", "доск", "бревн", "фанер", "дсп", "двп"))
    is_explicitly_metallic = any(w in q_lower for w in ("металл", "сталь", "профиль", "швеллер", "двутавр", "уголок"))

    if is_explicitly_metallic and not is_explicitly_wooden:
        if "деревян" in item_text:
            score *= 0.1
    elif is_explicitly_wooden and not is_explicitly_metallic:
        if "металл" in item_text:
            score *= 0.1

    return round(score, 6)


def _sha256_for_stat(path: str, mtime_ns: int, size: int) -> str:
    del mtime_ns, size
    from proxy.smeta_core.norm_revision import revision_fingerprint, revision_sha256
    resolved = Path(path).resolve()
    return revision_sha256(str(resolved), revision_fingerprint(resolved))


def _rag_manifest_path(base_path: Path) -> Path:
    """Resolve the active or explicitly staged smeta navigation manifest."""
    configured = os.getenv("LES_SMETA_NORM_RAG_MANIFEST", "").strip()
    return Path(configured) if configured else base_path.with_name(
        "les_smeta_norm_rag_manifest.json"
    )


def _rag_manifest_status(*, base_path: Path, collection: str, embedding_model: str) -> tuple[bool, str]:
    """Fail closed when a sibling vector index is stale or built by another embedder."""
    manifest_path = _rag_manifest_path(base_path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return False, "manifest_missing_or_invalid"
    if str(payload.get("status") or "") != "passed":
        return False, "manifest_not_passed"
    if str(payload.get("collection") or "") != collection:
        return False, "collection_mismatch"
    def model_identity(value: object) -> str:
        identity = str(value or "").strip().casefold()
        return identity[:-7] if identity.endswith(":latest") else identity

    if model_identity(payload.get("embedding_model")) != model_identity(embedding_model):
        return False, "embedding_model_mismatch"
    try:
        stat = base_path.stat()
        current_sha = _sha256_for_stat(str(base_path.resolve()), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return False, "base_unreadable"
    if str(payload.get("base_sha256") or "") != current_sha:
        return False, "base_revision_mismatch"
    return True, "compatible"


def _rag_index_mode(base_path: Path) -> str:
    try:
        payload = json.loads(_rag_manifest_path(base_path).read_text(encoding="utf-8"))
    except Exception:
        return ""
    return str(payload.get("index_mode") or "hybrid")


def _rag_dense_contract(base_path: Path) -> tuple[bool, str, str, str]:
    """Resolve the dedicated query backend from the active smeta generation.

    The general RAG ``EMBED_BACKEND`` belongs to the user-document index and is
    not evidence about the separately built smeta sibling index.  The active
    smeta manifest owns that immutable identity.  An explicit smeta override is
    allowed only when the manifest proves both backends share one embedding
    space; the HTTP embedding client still validates the backend actually used.
    """
    try:
        payload = json.loads(_rag_manifest_path(base_path).read_text(encoding="utf-8"))
    except Exception:
        return False, "manifest_missing_or_invalid", "", ""
    built_backend = str(payload.get("embedding_backend") or "").strip().lower()
    query_backend = (
        os.getenv("LES_SMETA_NORM_EMBED_BACKEND", "").strip().lower()
        or built_backend
    )
    if not built_backend:
        return False, "embedding_backend_missing", "", query_backend
    if built_backend == query_backend:
        return True, "same_backend", built_backend, query_backend
    verified_space = str(payload.get("embedding_space_id") or "").strip()
    expected_space = os.getenv("LES_SMETA_EMBEDDING_SPACE_ID", "").strip()
    if (
        payload.get("embedding_space_verified") is True
        and verified_space
        and expected_space
        and verified_space == expected_space
    ):
        return True, "verified_embedding_space", built_backend, query_backend
    return (
        False,
        f"embedding_backend_mismatch:{built_backend}!={query_backend or 'missing'}",
        built_backend,
        query_backend,
    )


def _rag_dense_compatibility(base_path: Path) -> tuple[bool, str]:
    compatible, reason, _built_backend, _query_backend = _rag_dense_contract(base_path)
    return compatible, reason


def _rag_cards_many(
    queries: list[str],
    *,
    limit: int,
    base_path: Path,
    trace: dict[str, Any] | None = None,
    base_types: tuple[str, ...] = (),
    collections: tuple[str, ...] = (),
) -> dict[str, list[dict[str, Any]]]:
    out = {query: [] for query in queries}
    collection = _rag_collection()
    if not collection or not queries:
        if trace is not None:
            trace.update({"status": "disabled", "reason": "collection_or_queries_missing"})
        return out
    embedding_model = _rag_embedding_model()
    if (base_types or collections) and not base_path.exists():
        if trace is not None:
            trace.update(status='blocked', reason='scope_requires_structured_base')
        return out
    try:
        compatible, reason = _rag_manifest_status(
            base_path=base_path,
            collection=collection,
            embedding_model=embedding_model,
        )
    except NormRevisionConflict as error:
        if trace is not None:
            trace.update(status='blocked', reason=error.reason, collection=collection,
                         normative_revision=dict(expected=error.expected, actual=error.actual))
        return out
    if not compatible:
        if trace is not None:
            trace.update({"status": "degraded_sparse_only", "reason": reason, "collection": collection})
        return out
    scope_connection = None
    client = None
    query_filter = None
    try:
        if base_types or collections:
            # The existing index has base_type/norm_key, not collection/bare_code.
            # Resolve collection membership once against a revision-checked SQL snapshot.
            if not base_path.exists():
                if trace is not None:
                    trace.update(status='blocked', reason='scope_requires_structured_base')
                return out
            scope_connection = _connect_base_readonly(base_path)
            scope_connection.row_factory = sqlite3.Row
            columns = {str(r['name']) for r in scope_connection.execute('PRAGMA table_info(norms)')}
            if not {'norm_key', 'base_type', 'bare_code'}.issubset(columns):
                if trace is not None:
                    trace.update(status='blocked', reason='scope_requires_structured_base')
                return out
            clauses, params = [], []
            if base_types:
                clauses.append('base_type IN (' + ','.join('?' for _ in base_types) + ')')
                params.extend(base_types)
            if collections:
                clauses.append('substr(bare_code,1,2) IN (' + ','.join('?' for _ in collections) + ')')
                params.extend(collections)
            keys = [str(r['norm_key']) for r in scope_connection.execute(
                'SELECT norm_key FROM norms WHERE ' + ' AND '.join(clauses) + ' ORDER BY norm_key', params)]
            if trace is not None:
                trace['scope'] = dict(strategy='payload_base_type+typed_norm_keys' if collections else 'payload_base_type',
                    base_types=list(base_types), collections=list(collections), norm_key_count=len(keys),
                    base_sha256=scope_connection.base_sha256)
            if not keys:
                if trace is not None:
                    trace.update(status='ok', reason='scope_empty', collection=collection)
                return out
            manifest = json.loads(_rag_manifest_path(base_path).read_text(encoding='utf-8'))
            if manifest.get('base_sha256') != scope_connection.base_sha256:
                if trace is not None:
                    trace.update(status='blocked', reason='base_revision_mismatch', collection=collection)
                return out
            conditions = [models.FieldCondition(key='base_sha256', match=models.MatchValue(value=scope_connection.base_sha256))]
            if base_types:
                conditions.append(models.FieldCondition(key='base_type', match=models.MatchAny(any=list(base_types))))
            if collections:
                conditions.append(models.FieldCondition(key='norm_key', match=models.MatchAny(any=keys)))
            query_filter = models.Filter(must=conditions)
        client = QdrantClient(trust_env=trust_env_for_url(os.getenv("QDRANT_URL", "http://127.0.0.1:6333")),
            url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
            timeout=60.0,
            check_compatibility=False,
        )
        if not client.collection_exists(collection):
            if trace is not None:
                trace.update({"status": "degraded_sparse_only", "reason": "collection_missing", "collection": collection})
            return out
        index_mode = _rag_index_mode(base_path)
        (
            dense_compatible,
            dense_reason,
            index_embedding_backend,
            query_embedding_backend,
        ) = _rag_dense_contract(base_path)
        embedding_ms = 0.0
        dense_vectors: list[Any] = [None] * len(queries)
        sparse_mode = index_mode in {"sparse_only", "building_dense"} or not dense_compatible
        if not sparse_mode:
            embed = EmbedClient(
                os.getenv("MLX_URL", "http://127.0.0.1:8080"),
                model=embedding_model,
                backend=query_embedding_backend,
            )
            embedding_started = perf_counter()
            dense_vectors = embed.encode_sync([prepare_query_for_embedding(query) for query in queries])
            embedding_ms = round((perf_counter() - embedding_started) * 1000, 2)
        rehydrated_counts: dict[str, int] = {}
        missing_counts: dict[str, int] = {}
        retrieval_started = perf_counter()
        for query, dense in zip(queries, dense_vectors, strict=True):
            sparse = encode_bm25(query)
            prefetch = []
            if dense is not None:
                prefetch.append(models.Prefetch(query=dense, using="dense", limit=max(24, limit * 3), filter=query_filter))
            if sparse:
                prefetch.append(models.Prefetch(
                    query=models.SparseVector(indices=list(sparse), values=list(sparse.values())),
                    using=SPARSE_VECTOR_NAME,
                    limit=max(24, limit * 3),
                    filter=query_filter,
                ))
            result = client.query_points(
                collection_name=collection,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=max(1, min(limit, 50)),
                with_payload=True,
                query_filter=query_filter,
            )
            keys = [str((point.payload or {}).get("norm_key") or "") for point in result.points]
            out[query] = _cards_by_norm_keys(keys, base_path=base_path, connection=scope_connection)
            rehydrated_counts[query] = len(out[query])
            missing_counts[query] = max(0, len([key for key in keys if key]) - len(out[query]))
        if trace is not None:
            trace.update({
                "status": "degraded_sparse_only" if sparse_mode else "ok",
                "reason": (
                    "dense_index_not_built"
                    if index_mode in {"sparse_only", "building_dense"}
                    else (dense_reason if not dense_compatible else "")
                ),
                "index_mode": index_mode,
                "dense_compatible": dense_compatible,
                "collection": collection,
                "embedding_model": embedding_model,
                "index_embedding_backend": index_embedding_backend,
                "query_embedding_backend": query_embedding_backend,
                "rehydrated_counts": rehydrated_counts,
                "missing_norm_keys": missing_counts,
                "embedding_ms": embedding_ms,
                "retrieval_ms": round((perf_counter() - retrieval_started) * 1000, 2),
            })
    except NormRevisionConflict as error:
        out.update({query: [] for query in queries})
        if trace is not None:
            trace.update(status='blocked', reason=error.reason,
                         normative_revision=dict(expected=error.expected, actual=error.actual))
    except Exception as exc:
        # Dense retrieval is an additive candidate channel. The caller still has
        # exact/FTS cards and exposes the degraded backend in its trace.
        if trace is not None:
            trace.update({"status": "degraded_sparse_only", "reason": type(exc).__name__, "collection": collection})
        return out
    finally:
        try:
            if client is not None:
                client.close()
        finally:
            if scope_connection is not None:
                try:
                    scope_connection.close()
                except NormRevisionConflict as error:
                    out.update({query: [] for query in queries})
                    if trace is not None:
                        trace.update(status='blocked', reason=error.reason,
                                     normative_revision=dict(expected=error.expected, actual=error.actual))
    return out


def _rrf_cards(*rankings: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    cards: dict[str, dict[str, Any]] = {}
    for ranking in rankings:
        for rank, card in enumerate(ranking, 1):
            identity = str(card.get("norm_key") or card.get("norm_code") or "")
            if not identity:
                continue
            cards.setdefault(identity, card)
            scores[identity] = scores.get(identity, 0.0) + 1.0 / (60.0 + rank)
    # Equal RRF scores must remain bit-stable regardless of input casing/order.
    ordered = sorted(
        cards,
        key=lambda identity: (
            -scores[identity],
            identity.casefold(),
            identity,
            str(cards[identity].get("norm_code") or "").casefold(),
        ),
    )
    return [cards[identity] for identity in ordered[:limit]]


def _coverage_merge(*rankings: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Round-robin variant heads before RRF remainder so no variant is hidden by a tie."""
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_depth = max((len(ranking) for ranking in rankings), default=0)
    for depth in range(max_depth):
        for ranking in rankings:
            if depth >= len(ranking):
                continue
            card = ranking[depth]
            identity = str(card.get("norm_key") or card.get("norm_code") or "")
            if not identity or identity in seen:
                continue
            seen.add(identity)
            output.append(card)
            if len(output) >= limit:
                return output
    return output


def _run_blocking(coro: Any) -> Any:
    """Await the configured async reranker from the synchronous browser."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _rerank_cards(
    query: str,
    cards: list[dict[str, Any]],
    *,
    limit: int,
    fuse_with_input: bool = True,
) -> tuple[list[dict[str, Any]], bool, str]:
    """Fuse cross-encoder order with hybrid retrieval and expose transport failure."""
    if os.getenv("LES_SMETA_NORM_RERANK", "true").strip().casefold() not in {
        "1", "true", "yes", "on",
    }:
        return cards[:limit], False, "disabled"
    if len(cards) <= 3:
        return cards[:limit], False, "pool_too_small"
    chunks = [
        {
            "text": "\n".join(filter(None, [
                str(card.get("title") or ""),
                str(card.get('table_heading') or ''),
                f"Измеритель: {card.get('measure_unit') or ''}",
                f"Состав: {'; '.join(str(step) for step in (card.get('work_steps') or [])[:8])}",
                "Ресурсы для проверки технологии: " + "; ".join(
                    str(item.get("name") or "")
                    for item in (card.get("resource_preview") or [])[:12]
                    if isinstance(item, dict) and str(item.get("name") or "").strip()
                ),
            ]))[:1600],
            "metadata": {"index": index},
            "score": 0.0,
        }
        for index, card in enumerate(cards)
    ]
    reranker_cls = select_reranker_cls()
    try:
        ranked = _run_blocking(
            reranker_cls(
                mlx_url=(
                    os.getenv("MLX_URL", "").strip()
                    or "http://127.0.0.1:8080"
                )
            ).rerank(
                query,
                chunks,
                top_k=len(cards),
            )
        )
        order = [
            int((getattr(item, "metadata", None) or {}).get("index", -1))
            for item in ranked
        ]
        valid_order = list(dict.fromkeys(index for index in order if 0 <= index < len(cards)))
        if not valid_order:
            raise RuntimeError("reranker returned no usable candidate order")
    except Exception as error:
        logger.warning(
            "[SMETA_RERANK] %s failed for %r; preserving raw RRF order: %s",
            reranker_cls.__name__,
            query[:80],
            error,
        )
        # Usable menu/order without cross-encoder — not a hard catalog failure.
        return cards[:limit], False, "fallback_input_order"
    reordered = [cards[index] for index in valid_order]
    used = set(valid_order)
    status = 'ok' if len(valid_order) == len(cards) else 'partial_response'
    if status == 'partial_response':
        logger.warning('[SMETA_RERANK] partial order: requested=%d returned=%d valid=%d missing=%d',
            len(cards), len(order), len(valid_order), len(cards) - len(valid_order))
    if not fuse_with_input:
        # An official catalog is ordered by code, not by relevance.  Its input
        # order must never be treated as an independent ranking signal.
        # Unscored official catalogue rows remain visible as an explicit fallback.
        reordered.extend(card for index, card in enumerate(cards) if index not in used)
        return reordered[:limit], True, status
    # A cross-encoder is a second relevance signal, not an oracle. Preserve
    # the complete native RRF input and only the actual vendor order. Missing
    # vendor rows must not receive a fabricated second relevance signal.
    return _rrf_cards(cards, reordered, limit=limit), True, status


def _fts_prefix(term: str) -> str:
    normalized = term.casefold().replace("ё", "е")
    if not normalized.isalpha() or len(normalized) < 5:
        return normalized
    for suffix in _RUSSIAN_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 4:
            return normalized[: -len(suffix)]
    return normalized[:-1] if len(normalized) >= 7 else normalized


def _fts_query(terms: list[str], *, prefix: bool, joiner: str) -> str:
    parts = []
    for term in terms:
        token = _fts_prefix(term) if prefix else term.casefold().replace("ё", "е")
        token = token.replace('"', "")
        if token:
            parts.append(f'"{token}"*' if prefix and token.isalpha() else f'"{token}"')
    return f" {joiner} ".join(parts)


def _typed_cards(
    query: str,
    *,
    limit: int,
    base_path: Path,
    base_types: tuple[str, ...] = (),
    collections: tuple[str, ...] = (),
    trace: dict[str, Any] | None = None,
) -> list[dict[str, Any]] | None:
    if trace is not None:
        trace.update(query=query, limit=limit, attempts=[], selected_mode=None, status='unavailable',
            filters=dict(base_types=list(base_types), collections=list(collections)))
    if not base_path.exists():
        return None
    conn = _connect_base_readonly(base_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        if "norms" not in tables or "norms_fts" not in tables:
            return None
        exact_key = _norm_key(query)
        filters: list[str] = []
        filter_params: list[Any] = []
        if base_types:
            filters.append("n.base_type IN (" + ",".join("?" for _ in base_types) + ")")
            filter_params.extend(base_types)
        if collections:
            filters.append("substr(n.bare_code,1,2) IN (" + ",".join("?" for _ in collections) + ")")
            filter_params.extend(collections)
        filter_sql = (" AND " + " AND ".join(filters)) if filters else ""
        if exact_key:
            rows = conn.execute(
                "SELECT n.* FROM norms n WHERE n.norm_key = ?" + filter_sql + " LIMIT ?",
                (exact_key, *filter_params, limit),
            ).fetchall()
            if trace is not None:
                trace['attempts'].append(dict(mode='exact_key', norm_key=exact_key, count=len(rows)))
                trace['selected_mode'] = 'exact_key'
        else:
            # Keep numeric literals and the entire query. FTS5 unicode61 splits
            # decimal punctuation in the index; a quoted decimal is a phrase,
            # so both 0,8 and 0.8 match the same adjacent tokens without losing
            # the fraction or turning a single digit into an omitted condition.
            terms = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+(?:[.,][0-9]+)?", query)
            if trace is not None:
                trace.update(term_limit=None, terms_used=terms, terms_omitted=[])
            if not terms:
                if trace is not None:
                    trace['status'] = 'no_terms'
                return []
            rows = []
            queries = [
                ('strict_and', _fts_query(terms, prefix=False, joiner="AND")),
                ('prefix_and', _fts_query(terms, prefix=True, joiner="AND")),
            ]
            if len(terms) > 1:
                queries.append(('prefix_or', _fts_query(terms, prefix=True, joiner="OR")))
            executed = set()
            for mode, fts_query in queries:
                if not fts_query or fts_query in executed:
                    continue
                executed.add(fts_query)
                rows = conn.execute(
                    """
                    SELECT n.* FROM norms_fts f
                    JOIN norms n ON n.norm_key = f.norm_key
                    WHERE norms_fts MATCH ?
                    {filter_sql}
                    ORDER BY bm25(norms_fts, 0.0, 6.0, 1.0), n.norm_key
                    LIMIT ?
                    """.format(filter_sql=filter_sql),
                    (fts_query, *filter_params, limit),
                ).fetchall()
                if trace is not None:
                    trace['attempts'].append(dict(mode=mode, fts_query=fts_query, count=len(rows)))
                if rows:
                    if trace is not None:
                        trace['selected_mode'] = mode
                    break
        if trace is not None:
            trace.update(status='matched' if rows else 'no_matches', returned_count=len(rows))
        return [_card(conn, row) for row in rows]
    finally:
        conn.close()


def search_rows(words: list[str]) -> list[SmetaNormRow]:
    """Legacy adapter during migration; it returns candidates, never a binding."""
    return get_smeta_norm_store().search_rows(words)


def browse_norm_catalog(
    *,
    family: str = "",
    collection: str = "",
    section: str = "",
    table: str = "",
    limit: int = 100,
    base_path: str | Path | None = None,
) -> dict[str, Any]:
    """Navigate typed FSNB identity without skipping hierarchy levels.

    The public ``section`` level is the encoded child below a collection, for
    example ``10-04``.  The official source may call that node ``Отдел 4`` and
    may contain additional textual ``Раздел``/``Подраздел`` headings.  Those
    official labels remain visible on table nodes.
    """
    path = Path(base_path) if base_path is not None else _base_path()
    integrity = normative_base_integrity(base_path=path)
    if not path.exists():
        return {
            "schema": "smeta_norm_catalog_v1",
            "level": "missing",
            "items": [],
            "source_integrity": integrity,
        }
    bounded_limit = max(1, min(int(limit), 1000))
    family_value = str(family or "").strip()
    collection_value = re.sub(r"\D", "", str(collection or ""))[:2]
    section_value = _section_code(section, collection=collection_value)
    table_value = re.sub(r"[^0-9-]", "", str(table or "")).strip("-")
    conn = _connect_base_readonly(path)
    conn.row_factory = sqlite3.Row
    try:
        current_node = {
            "node_id": "catalog:root",
            "parent_id": "",
            "node_type": "root",
            "cipher": "ФСНБ",
            "title": "Федеральная сметная нормативная база",
            "description": "Официальная иерархия видов сметных норм",
            "source_ref": "ФСНБ-2022",
            "edition": "ФСНБ-2022",
        }
        collection_passport: dict[str, Any] = {}
        if not family_value:
            level = "family"
            rows = conn.execute(
                "SELECT base_type key, count(*) norm_count, sum(resource_count) resource_count "
                "FROM norms GROUP BY base_type ORDER BY base_type LIMIT ?",
                (bounded_limit,),
            ).fetchall()
        elif not collection_value:
            level = "collection"
            rows = conn.execute(
                "SELECT substr(bare_code,1,2) key, count(*) norm_count, "
                "sum(resource_count) resource_count, min(source_doc) source_example "
                "FROM norms WHERE base_type=? "
                "GROUP BY substr(bare_code,1,2) ORDER BY key LIMIT ?",
                (family_value, bounded_limit),
            ).fetchall()
        elif not section_value and not table_value:
            level = "section"
            rows = conn.execute(
                "SELECT substr(bare_code,1,5) key, count(*) norm_count, "
                "sum(resource_count) resource_count, min(source_doc) source_example FROM norms "
                "WHERE base_type=? AND substr(bare_code,1,2)=? "
                "GROUP BY substr(bare_code,1,5) ORDER BY key LIMIT ?",
                (family_value, collection_value, bounded_limit),
            ).fetchall()
            collection_passport = _collection_passport(
                conn,
                family=family_value,
                collection=collection_value,
            )
        elif not table_value:
            level = "table"
            rows = conn.execute(
                "SELECT substr(bare_code,1,9) key, count(*) norm_count, "
                "sum(resource_count) resource_count, min(source_doc) source_example, "
                "group_concat(norm_name, char(31)) norm_names FROM norms "
                "WHERE base_type=? AND substr(bare_code,1,2)=? "
                "AND substr(bare_code,1,5)=? "
                "GROUP BY substr(bare_code,1,9) ORDER BY key LIMIT ?",
                (family_value, collection_value, section_value, bounded_limit),
            ).fetchall()
        else:
            level = "norm"
            normalized_table = table_value[:9]
            if collection_value and not normalized_table.startswith(
                f"{collection_value}-"
            ):
                return {
                    "schema": "smeta_norm_catalog_v1",
                    "level": level,
                    "selection_owner": "model_or_user",
                    "filters": {
                        "family": family_value,
                        "collection": collection_value,
                        "section": section_value,
                        "table": normalized_table,
                    },
                    "source_integrity": integrity,
                    "items": [],
                }
            if section_value and not normalized_table.startswith(
                f"{section_value}-"
            ):
                return {
                    "schema": "smeta_norm_catalog_v1",
                    "level": level,
                    "selection_owner": "model_or_user",
                    "filters": {
                        "family": family_value,
                        "collection": collection_value,
                        "section": section_value,
                        "table": normalized_table,
                    },
                    "source_integrity": integrity,
                    "items": [],
                }
            rows = conn.execute(
                "SELECT * FROM norms WHERE base_type=? "
                "AND substr(bare_code,1,2)=? AND substr(bare_code,1,9)=? "
                "ORDER BY bare_code LIMIT ?",
                (family_value, collection_value, normalized_table, bounded_limit),
            ).fetchall()
            norm_items = []
            for row in rows:
                card = _card(conn, row)
                norm_code = str(card.get("norm_code") or row["bare_code"] or "")
                card.update({
                    "node_id": str(card.get("norm_key") or ""),
                    "parent_id": f"catalog:table:{family_value}:{normalized_table}",
                    "node_type": "norm",
                    "cipher": norm_code,
                    "edition": "ФСНБ-2022",
                })
                norm_items.append(card)
            return {
                "schema": "smeta_norm_catalog_v1",
                "level": level,
                "current_node": {
                    "node_id": f"catalog:table:{family_value}:{normalized_table}",
                    "parent_id": f"catalog:section:{family_value}:{normalized_table[:5]}",
                    "node_type": "table",
                    "cipher": normalized_table,
                    "title": normalized_table,
                    "description": "Официальная таблица ФСНБ",
                    "source_ref": f"ФСНБ-2022 · {family_value}, таблица {normalized_table}",
                    "edition": "ФСНБ-2022",
                },
                "selection_owner": "model_or_user",
                "filters": {
                    "family": family_value,
                    "collection": collection_value,
                    "section": section_value,
                    "table": normalized_table,
                },
                "source_integrity": integrity,
                "items": norm_items,
            }
        if level == "family":
            items = [_family_catalog_item(row) for row in rows]
        elif level == "collection":
            items = [
                _collection_catalog_item(row, family=family_value)
                for row in rows
            ]
        elif level == "section":
            items = [
                _section_catalog_item(row, family=family_value)
                for row in rows
            ]
        elif level == "table":
            items = [
                _table_catalog_item(row, family=family_value)
                for row in rows
            ]
        else:
            items = [dict(row) for row in rows]
        result = {
            "schema": "smeta_norm_catalog_v1",
            "level": level,
            "current_node": current_node,
            "selection_owner": "model_or_user",
            "filters": {
                "family": family_value,
                "collection": collection_value,
                "section": section_value,
                "table": table_value,
            },
            "source_integrity": integrity,
            "items": items,
        }
        if level == "collection":
            result["current_node"] = {
                "node_id": f"catalog:family:{family_value}",
                "parent_id": "catalog:root",
                "node_type": "family",
                "cipher": family_value,
                "title": family_value,
                "description": "Официальный вид сметных норм",
                "source_ref": f"ФСНБ-2022 · {family_value}",
                "edition": "ФСНБ-2022",
            }
        elif level == "section":
            result["current_node"] = {
                "node_id": f"catalog:collection:{family_value}:{collection_value}",
                "parent_id": f"catalog:family:{family_value}",
                "node_type": "collection",
                "cipher": collection_value,
                "title": str(collection_passport.get("title") or collection_value),
                "description": str(
                    collection_passport.get("purpose")
                    or "Официальный сборник ФСНБ"
                ),
                "source_ref": str(
                    collection_passport.get("source_ref")
                    or f"ФСНБ-2022 · {family_value}, сборник {collection_value}"
                ),
                "edition": "ФСНБ-2022",
            }
        elif level == "table":
            result["current_node"] = {
                "node_id": f"catalog:section:{family_value}:{section_value}",
                "parent_id": f"catalog:collection:{family_value}:{collection_value}",
                "node_type": "section",
                "cipher": section_value,
                "title": section_value,
                "description": "Официальный раздел каталога ФСНБ",
                "source_ref": f"ФСНБ-2022 · {family_value}, раздел каталога {section_value}",
                "edition": "ФСНБ-2022",
            }
        if collection_passport:
            result["collection_passport"] = collection_passport
        return result
    finally:
        conn.close()


def rank_norm_catalog_collections(
    query: str,
    *,
    family: str,
    limit: int = 8,
    base_path: str | Path | None = None,
) -> dict[str, Any]:
    """Rank official collection nodes before searching individual norms.

    This is a bounded typed catalog graph, not a professional selector:
    ``family -> collection`` edges and their official titles/sections only
    produce a model-visible navigation menu.  Norm evidence is still retrieved
    later by a scoped ``search_norms_batch`` and hydrated from typed SQLite.
    """
    started = perf_counter()
    catalog = browse_norm_catalog(
        family=family,
        limit=1000,
        base_path=base_path,
    )
    catalog_items = [
        item for item in (catalog.get("items") or []) if isinstance(item, dict)
    ]
    cards: list[dict[str, Any]] = []
    for item in catalog_items:
        collection = str(item.get("key") or "")
        if not collection:
            continue
        source_lines = _source_lines(item.get("source_example"))
        cards.append({
            **item,
            "norm_key": f"catalog_collection:{family}:{collection}",
            "norm_code": f"{family}:{collection}",
            "family": family,
            "collection": collection,
            "navigation_kind": "collection",
            "title": str(item.get("title") or item.get("purpose") or ""),
            "work_steps": [
                str(item.get("purpose") or ""),
                *source_lines[:12],
            ],
        })
    ranked, reranked, rerank_status = _rerank_cards(
        str(query or ""),
        cards,
        limit=max(1, min(len(cards), 100)),
        fuse_with_input=False,
    )
    query_variants = _query_variants(query, stage="collection") or [str(query or "")]
    rerank_rank = {
        str(card.get("collection") or ""): rank
        for rank, card in enumerate(ranked, start=1)
    }
    compass_scores = {
        str(card.get("collection") or ""): max(
            catalog_compass_score(variant, card)
            for variant in query_variants
        )
        for card in cards
    }
    compass_order = sorted(
        (
            collection
            for collection, score in compass_scores.items()
            if collection and score > 0.0
        ),
        key=lambda collection: (
            -compass_scores[collection],
            collection,
        ),
    )
    compass_rank = {
        collection: rank
        for rank, collection in enumerate(compass_order, start=1)
    }
    by_collection = {
        str(card.get("collection") or ""): card for card in cards
    }
    # Protect exact official catalog heads from a semantically plausible but
    # wrong cross-encoder order. This is candidate coverage, not a selected
    # collection: the model still receives and compares the bounded menu.
    fused_collections = list(
        dict.fromkeys([
            *compass_order,
            *(
                str(card.get("collection") or "")
                for card in ranked
                if str(card.get("collection") or "")
            ),
        ])
    )[: max(1, min(int(limit), 100))]
    visible_cards = []
    for rank, collection in enumerate(fused_collections, start=1):
        card = by_collection[collection]
        visible_cards.append({
            key: value
            for key, value in {
                **card,
                "catalog_rank": rank,
                "rerank_rank": rerank_rank.get(collection),
                "catalog_compass_rank": compass_rank.get(collection),
                "catalog_compass_score": compass_scores.get(collection, 0.0),
            }.items()
            if key not in {"norm_key", "norm_code", "work_steps"}
        })
    return {
        "schema": "smeta_norm_catalog_graph_v1",
        "level": "collection",
        "family": family,
        "selection_owner": "model_or_user",
        "cards": visible_cards,
        "source_integrity": catalog.get("source_integrity"),
        "retrieval_trace": {
            "retrieval_policy": "typed_catalog_lexical_rrf_rerank",
            "graph_route": ["family", "collection"],
            "catalog_nodes": len(cards),
            "returned_candidates": len(visible_cards),
            "reranked": reranked,
            "rerank_status": rerank_status,
            "query_variants": query_variants,
            "fusion": "official_lexical_head_coverage_then_rerank",
            "signals": ["official_catalog_lexical", "rerank"],
            "tool_total_ms": round((perf_counter() - started) * 1000, 2),
        },
    }


def rank_norm_catalog_tables(
    query: str,
    *,
    family: str,
    collection: str,
    section: str,
    limit: int = 12,
    base_path: str | Path | None = None,
) -> dict[str, Any]:
    """Rank typed table nodes only inside one model-selected section."""
    started = perf_counter()
    catalog = browse_norm_catalog(
        family=family,
        collection=collection,
        section=section,
        limit=1000,
        base_path=base_path,
    )
    cards: list[dict[str, Any]] = []
    for item in catalog.get("items") or []:
        if not isinstance(item, dict):
            continue
        table_code = str(item.get("key") or "")
        if not table_code:
            continue
        cards.append({
            **item,
            "norm_key": f"catalog_table:{family}:{table_code}",
            "norm_code": f"{family}:{table_code}",
            "family": family,
            "collection": collection,
            "section": _section_code(section, collection=collection),
            "navigation_kind": "table",
            "work_steps": [
                str(item.get("purpose") or ""),
                *[str(value) for value in (item.get("hierarchy") or [])],
                *[
                    str(value)
                    for value in (item.get("norm_name_examples") or [])[:12]
                ],
            ],
        })
    ranked, reranked, rerank_status = _rerank_cards(
        str(query or ""),
        cards,
        limit=max(1, min(int(limit), 100)),
        fuse_with_input=False,
    )
    visible_cards = []
    for rank, card in enumerate(ranked, start=1):
        visible_cards.append({
            key: value
            for key, value in {**card, "catalog_rank": rank}.items()
            if key not in {"norm_key", "norm_code", "work_steps"}
        })
    return {
        "schema": "smeta_norm_catalog_graph_v1",
        "level": "table",
        "family": family,
        "collection": collection,
        "section": _section_code(section, collection=collection),
        "selection_owner": "model_or_user",
        "cards": visible_cards,
        "source_integrity": catalog.get("source_integrity"),
        "retrieval_trace": {
            "retrieval_policy": "typed_catalog_graph_then_rerank",
            "graph_route": ["family", "collection", "section", "table"],
            "catalog_nodes": len(cards),
            "returned_candidates": len(visible_cards),
            "reranked": reranked,
            "rerank_status": rerank_status,
            "tool_total_ms": round((perf_counter() - started) * 1000, 2),
        },
    }


def browse_norms(
    query: str, *, limit: int = 8, base_path: str | Path | None = None,
    expand_queries: bool = True,
) -> dict[str, Any]:
    return browse_norms_many(
        [query], limit=limit, base_path=base_path, rerank=True,
        expand_queries=expand_queries,
    )[str(query)]


# Шифр нормы или таблицы, написанный прямо в запросе: «ГЭСНм08-02-395»,
# «ГЭСНм11-04-028-01», «ТЕРм10-01-055». Семейство (ГЭСН/ТЕР/ФЕР) и часть (м/р/п)
# разбираются отдельно от номера: в базе они лежат в разных колонках, и без разбора
# «08-02-395» совпадает и с ГЭСНм08, и с ГЭСН08.
CODE_IN_QUERY = re.compile(
    r"(?:^|[\s(«\"'])(?:ГЭСН|ТЕР|ФЕР)(м|р|п|мр)?(\d{2}-\d{2}-\d{3}(?:-\d{2})?)(?=$|[\s),.;:»\"'])",
    re.IGNORECASE,
)


def code_lookup_request(query: str) -> tuple[str, str] | None:
    """Шифр из запроса как пара «семейство базы, номер»; None, если шифра нет.

    Запрос с шифром — это не поиск по смыслу, а обращение к конкретной норме или
    таблице. Векторный поиск на «ГЭСНм08-02-395» отвечал `ГЭСНм20-02-002-14`, то есть
    цеплялся за цифры в чужих шифрах, и модель, пришедшая посмотреть варианты таблицы,
    получала выдумку вместо перечня (ревью Codex 11.09).
    """
    match = CODE_IN_QUERY.search(str(query or ""))
    if not match:
        return None
    part = (match.group(1) or "").lower()
    # Территориальная и федеральная расценки отличаются от нормы только семейством:
    # в активной базе лежат ГЭСН, и шифр ТЕР указывает на ту же таблицу.
    return f"ГЭСН{part}", match.group(2)


def _code_listing(
    family: str,
    number: str,
    *,
    base_path: Path,
    base_types: tuple[str, ...] = (),
    collections: tuple[str, ...] = (),
) -> list[dict[str, Any]] | None:
    """Нормы по точному шифру или все варианты таблицы — в порядке публикации."""
    if not base_path.exists():
        return None
    conn = _connect_base_readonly(base_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        if "norms" not in tables:
            return None
        # Полный шифр отдаёт одну норму, шифр таблицы — все её варианты. Разделяет их
        # длина номера, а не отдельный флаг: «08-02-395» и «08-02-395-01» приходят из
        # одного и того же текста запроса.
        exact = len(number.split("-")) == 4
        if base_types and family not in base_types:
            return []
        collection_sql = ''
        params: list[Any] = [family, number]
        if collections:
            collection_sql = ' AND substr(bare_code,1,2) IN (' + ','.join('?' for _ in collections) + ')'
            params.extend(collections)
        rows = conn.execute(
            "SELECT * FROM norms WHERE base_type = ? AND "
            + ("bare_code = ?" if exact else "substr(bare_code,1,9) = ?")
            + collection_sql + " ORDER BY bare_code",
            params,
        ).fetchall()
        return [_card(conn, row, full_resources=exact) for row in rows]
    finally:
        conn.close()


def _table_listing(
    table_codes: tuple[str, ...],
    *,
    base_path: Path,
    base_types: tuple[str, ...] = (),
    collections: tuple[str, ...] = (),
) -> list[dict[str, Any]] | None:
    """Return the complete official table menu in published code order."""
    if not base_path.exists() or not table_codes:
        return None
    conn = _connect_base_readonly(base_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        if "norms" not in tables:
            return None
        placeholders = ",".join("?" for _ in table_codes)
        family_filter = ""
        params: list[Any] = list(table_codes)
        if base_types:
            family_filter = (
                " AND base_type IN ("
                + ",".join("?" for _ in base_types)
                + ")"
            )
            params.extend(base_types)
        if collections:
            family_filter += ' AND substr(bare_code,1,2) IN (' + ','.join('?' for _ in collections) + ')'
            params.extend(collections)
        rows = conn.execute(
            f"SELECT * FROM norms WHERE substr(bare_code,1,9) IN ({placeholders}) "
            f"{family_filter} ORDER BY base_type, bare_code",
            params,
        ).fetchall()
        return [_card(conn, row) for row in rows]
    finally:
        conn.close()


def browse_norms_many(
    queries: list[str],
    *,
    limit: int = 8,
    base_path: str | Path | None = None,
    base_types: list[str] | tuple[str, ...] | None = None,
    collections: list[str] | tuple[str, ...] | None = None,
    table_codes: list[str] | tuple[str, ...] | None = None,
    rerank: bool | None = None,
    expand_queries: bool = True,
) -> dict[str, dict[str, Any]]:
    tool_started = perf_counter()
    bounded_limit = max(1, min(int(limit), 50))
    pool_limit = min(50, max(bounded_limit, bounded_limit * 4, 24))
    path = Path(base_path) if base_path is not None else _base_path()
    integrity = normative_base_integrity(base_path=path)
    clean_queries = list(dict.fromkeys(str(query).strip() for query in queries if str(query).strip()))
    clean_base_types = tuple(dict.fromkeys(str(value).strip() for value in (base_types or ()) if str(value).strip()))
    clean_collections = tuple(dict.fromkeys(
        re.sub(r"\D", "", str(value))[:2] for value in (collections or ()) if re.sub(r"\D", "", str(value))
    ))
    clean_table_codes = tuple(dict.fromkeys(
        code
        for value in (table_codes or ())
        if (code := re.sub(r"[^0-9-]", "", str(value)).strip("-")[:9])
    ))[:20]
    if clean_table_codes:
        listing = _table_listing(
            clean_table_codes,
            base_path=path,
            base_types=clean_base_types,
            collections=clean_collections,
        )
        return {
            query: {
                "schema": "smeta_norm_browse_v1",
                "query": query,
                "backend": (
                    "official_table_listing"
                    if listing is not None
                    else "structured_base_unavailable"
                ),
                "selection_owner": "model_or_user",
                "selected_code": "",
                "source_integrity": integrity,
                "cards": list(listing or []),
                "retrieval_trace": {
                    "lexical_candidates": len(listing or []),
                    "rag_candidates": 0,
                    "fusion_candidates": len(listing or []),
                    "returned_candidates": len(listing or []),
                    "rerank_deferred": False,
                    "reranked": False,
                    "rerank_status": "not_needed_table_listing",
                    "complete_table": listing is not None,
                    "truncated": False,
                    "filters": {
                        "base_types": list(clean_base_types),
                        "collections": list(clean_collections),
                        "table_codes": list(clean_table_codes),
                    },
                    "query_variants": [query] if query else [],
                    "tool_total_ms": round((perf_counter() - tool_started) * 1000, 2),
                    "queries_count": len(queries),
                    "unique_queries_count": len(clean_queries),
                },
            }
            for query in (clean_queries or [""])
        }
    # Запрос с шифром обслуживается точным перечнем из базы, а не поиском по смыслу.
    # Это делается до разбора на варианты: на «ГЭСНм08-02-395» векторный поиск отвечал
    # `ГЭСНм20-02-002-14` и `ГЭСН28-02-022-05`, цепляясь за цифры в чужих шифрах.
    by_code: dict[str, dict[str, Any]] = {}
    for query in clean_queries:
        request = code_lookup_request(query)
        if request is None:
            continue
        listing = _code_listing(request[0], request[1], base_path=path,
                                base_types=clean_base_types, collections=clean_collections)
        # Empty means no matching code in the explicit scope; None is an unavailable reader.
        # An unavailable exact reader is a technical blocker, never a reason
        # to substitute a different vector norm for the model's literal code.
        unavailable = listing is None
        scope_excludes_code = (bool(clean_base_types and request[0] not in clean_base_types)
                               or bool(clean_collections and request[1][:2] not in clean_collections))
        listing = listing or []
        by_code[query] = {
            "schema": "smeta_norm_browse_v1",
            "query": query,
            "backend": "structured_base_unavailable" if unavailable else "official_code_listing",
            "selection_owner": "model_or_user",
            "selected_code": "",
            "source_integrity": integrity,
            "cards": listing[:pool_limit],
            "retrieval_trace": {
                "lexical_candidates": len(listing),
                "rag_candidates": 0,
                "fusion_candidates": len(listing),
                "returned_candidates": len(listing[:pool_limit]),
                "rerank_deferred": False,
                "reranked": False,
                "rerank_status": "not_needed_code_listing",
                # Ветка `rag` обязательна: исследование модели считает запрос
                # заблокированным, если её нет или статус не «ok», и роняет весь проход
                # с 503. На проходах 3 и 4 прогона 11.09 так и вышло — стоило модели
                # написать шифр в запросе. Поиск здесь не выполнялся, о чём сказано
                # прямо, но и препятствий нет: ответ взят из активной базы.
                "rag": {
                    "status": "blocked" if unavailable else "ok",
                    "reason": "structured_base_unavailable" if unavailable else (
                        "explicit_scope_excludes_code" if scope_excludes_code else "not_needed_code_listing"),
                    "collection": _rag_collection(),
                    "used": False,
                },
                "complete_table": len(request[1].split("-")) == 3,
                "code_request": {"base_type": request[0], "number": request[1]},
                "truncated": len(listing) > pool_limit,
                "filters": {
                    "base_types": list(clean_base_types) or [request[0]],
                    "collections": list(clean_collections),
                    "table_codes": [request[1]],
                },
                "query_variants": [query],
                "tool_total_ms": round((perf_counter() - tool_started) * 1000, 2),
                "queries_count": len(queries),
                "unique_queries_count": len(clean_queries),
            },
        }
    if by_code:
        clean_queries = [query for query in clean_queries if query not in by_code]
        if not clean_queries:
            return by_code

    # The configured cross-encoder owns batching. A document with many rows
    # must receive the same retrieval contract as a one-row query.
    rerank_enabled = bool(rerank) if rerank is not None else True
    variants_by_query = {
        query: (
            _query_variants(query)
            if expand_queries
            else [query]
        )
        for query in clean_queries
    }
    all_variants = list(dict.fromkeys(
        variant for query in clean_queries for variant in variants_by_query.get(query) or [query]
    ))
    rag_trace: dict[str, Any] = {}
    scope_args = {'base_types': clean_base_types, 'collections': clean_collections} if clean_base_types or clean_collections else {}
    rag_by_query = _rag_cards_many(all_variants, limit=pool_limit, base_path=path, trace=rag_trace, **scope_args)
    out: dict[str, dict[str, Any]] = {}
    rerank_ms = 0.0
    for query in clean_queries:
        query_variants = variants_by_query.get(query) or [query]
        lexical_rankings = []
        lexical_variants = []
        for variant in query_variants:
            lexical_trace: dict[str, Any] = {}
            lexical_rankings.append(_typed_cards(
                variant,
                limit=pool_limit,
                base_path=path,
                base_types=clean_base_types,
                collections=clean_collections,
                trace=lexical_trace,
            ))
            lexical_variants.append(lexical_trace)
        lexical_lists = [ranking for ranking in lexical_rankings if ranking is not None]
        lexical = _coverage_merge(*lexical_lists, limit=pool_limit) if lexical_lists else None
        backend = "typed_sqlite_fts"
        if lexical is None:
            backend = "legacy_navigation_only"
            words = [word for word in query.split() if word]
            lexical = [
                {
                    "norm_code": row.code,
                    "title": row.title,
                    "measure_unit": row.measure_unit,
                    "profile": row.profile(),
                }
                for row in search_rows(words)[:pool_limit]
            ]
            if clean_base_types or clean_collections:
                # Legacy rows have no typed scope provenance; do not widen the selection.
                lexical = []
                backend = 'structured_scope_unavailable'
        rag_variant_lists = [rag_by_query.get(variant) or [] for variant in query_variants]
        rag_merged = _coverage_merge(*rag_variant_lists, limit=pool_limit) if rag_variant_lists else []
        rag_cards = [
            card for card in rag_merged
            if (not clean_base_types or str(card.get("base_type") or "") in clean_base_types)
            and (
                not clean_collections
                or re.sub(r"\D", "", str(card.get("norm_code") or ""))[:2] in clean_collections
            )
        ]
        # Qdrant performs dense+sparse RRF internally; fuse that hybrid ranking
        # with the independent typed/FTS safety channel through RRF as well.
        # No channel is allowed to become a hidden selector for the model.
        # The per-channel pool is already bounded. Do not cut their union before
        # the cross-encoder has seen it: a tail candidate from either channel
        # may be the best match. RRF deduplicates by typed norm identity; the
        # requested output limit is applied after reranking (or to the fallback).
        fused = _rrf_cards(lexical, rag_cards, limit=len(lexical) + len(rag_cards)) if rag_cards else lexical
        cards = fused[:bounded_limit]
        reranked = False
        rerank_status = "not_attempted"
        if rag_cards:
            backend = f"{backend}+smeta_norm_qdrant_hybrid"
        if rerank_enabled:
            rerank_started = perf_counter()
            cards, reranked, rerank_status = _rerank_cards(
                query,
                fused,
                limit=bounded_limit,
            )
            rerank_ms += (perf_counter() - rerank_started) * 1000
            if reranked:
                backend = f"{backend}+bge_rerank_rrf"
            else:
                backend = f"{backend}+rerank_{rerank_status}"
        else:
            rerank_status = "disabled_by_caller"
            backend = f"{backend}+rerank_deferred"
        out[query] = {
            "schema": "smeta_norm_browse_v1",
            "query": query,
            "backend": backend,
            "selection_owner": "model_or_user",
            "selected_code": "",
            "source_integrity": integrity,
            "retrieval_trace": {
                "lexical_candidates": len(lexical),
                "rag_candidates": len(rag_cards),
                "fusion_candidates": len(fused),
                "returned_candidates": len(cards),
                "rerank_deferred": bool(rag_cards and not rerank_enabled),
                "reranked": reranked,
                "rerank_status": rerank_status,
                "rag": dict(rag_trace),
                "filters": {"base_types": list(clean_base_types), "collections": list(clean_collections)},
                "query_variants": query_variants,
                "lexical_variants": lexical_variants,
                "query_expansion": bool(expand_queries),
                "embedding_ms": float(rag_trace.get("embedding_ms") or 0.0),
                "retrieval_ms": float(rag_trace.get("retrieval_ms") or 0.0),
                "rerank_ms": round(rerank_ms, 2),
                "tool_total_ms": round((perf_counter() - tool_started) * 1000, 2),
                "queries_count": len(queries),
                "unique_queries_count": len(clean_queries),
            },
            "cards": cards,
        }
    batch_total_ms = round((perf_counter() - tool_started) * 1000, 2)
    for result in out.values():
        trace = result.get("retrieval_trace") or {}
        trace["rerank_ms"] = round(rerank_ms, 2)
        trace["tool_total_ms"] = batch_total_ms
    # Ответы по шифру собраны до поиска и в общий разбор не попадали: возвращаются
    # рядом, иначе запрос с шифром остался бы вовсе без ответа.
    return {**by_code, **out}
