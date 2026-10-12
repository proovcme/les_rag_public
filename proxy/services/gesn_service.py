"""ГЭСН: норма → ресурсы (расход труда/машин/материалов на единицу) → строки для сборки ЛСР.

Замыкает конвейер ценообразования: позиция {код ГЭСН, объём} → ресурсы (через норму) → дальше
их пайплайн lsr_assembly (цены ФГИС ЦС/КАЦ → ОЗП/ЭМ/М → стеснённость → НР/СП → Всего). 0 LLM.

Норма даёт КОЛИЧЕСТВА на единицу; `expand_position(code, qty)` умножает на объём позиции →
строки ресурсов (kind/name/code/qty[/price]). Цены машин/материалов резолвятся по code из ФГИС ЦС
в сборке (если в норме нет снимка price); ОЗП/ОТм идут тарифом (price).

Два источника норм (объединяются прозрачно):
- **Семя** `config/domain/gesn_seed.yaml` — демо-норма эталона (выверена под gold-тест).
- **База** `data/smeta_base/les_smeta_base.sqlite` — runtime-facing structured ГЭСН-2022
  (`norm_key=<base_type>:<bare_code>`), собирается из source parquet ФГИС ЦС. Если базы нет —
  работаем на source parquet fallback или семени.
  При совпадении кода **семя побеждает** (эталон остаётся точным).
"""

from __future__ import annotations

import re
import json
import os
import sqlite3
from collections import OrderedDict, namedtuple
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from threading import RLock
from backend.runtime_paths import mutable_path
from typing import Any, Optional, Mapping
from proxy.smeta_core.norm_revision import (
    IDENTITY_FIELDS, IDENTITY_SCHEMA, NormRevisionConflict, identity_for_row,
    readonly_revision_connection, revision_fingerprint, revision_sha256,
)
from proxy.smeta_core.resource_identity import normalise_resource, resource_dedupe_key, dedupe_resources, labor_tariff_code

DEFAULT_PATH = Path("config/domain/gesn_seed.yaml")
DEFAULT_BASE_PATH = mutable_path("data/gesn_base/gesn2022.parquet")
DEFAULT_BASE_V2_PATH = mutable_path("data/gesn_base/gesn2022_v2.parquet")
DEFAULT_UNIFIED_BASE_PATH = mutable_path("data/gesn_base/gesn2022_unified.parquet")
DEFAULT_STRUCTURED_BASE_PATH = mutable_path("data/smeta_base/les_smeta_base.sqlite")

# Старые базы могли хранить труд как «Средний разряд работы N,M» без кода.
# Выводим тарифный код 1-100-NM (эталон: разряд 2,5 → 1-100-25) как fallback; новый FGIS-парсер
# сохраняет тариф сразу. Машинист-агрегат без разряда → код не выводим (флаг «нет цены»).
_LABOR_RAZRYAD_RE = re.compile(r"разряд\D*(\d)[.,](\d)")


def _labor_tariff_code(name: Any) -> Optional[str]:
    return labor_tariff_code(name)

# Префикс базы перед шифром. Важно не схлопывать разные базы с одинаковым номером:
# ГЭСН38-01-001-01 и ГЭСНм38-01-001-01 — разные нормы.
_BARE_NORM_RE = re.compile(r"\d{2}-\d{2}-\d{3}-\d{2}")
_BASE_PREFIX_RE = re.compile(
    r"^(ГЭСНМР|ГЭСНМ|ГЭСНП|ГЭСНР|ГЭСН|ФЕРМР|ФЕРМ|ФЕРП|ФЕРР|ФЕР|ТЕРМР|ТЕРМ|ТЕРП|ТЕРР|ТЕР)",
    re.I,
)
_TYPOGRAPHIC_DASHES = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
})


def _norm_transport_text(code: Any) -> str:
    return str(code or "").translate(_TYPOGRAPHIC_DASHES).strip().upper().replace(" ", "")


def _f(value: Any) -> float:
    try:
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _resource_text_key(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).casefold()


def _resource_number_key(value: Any) -> str:
    if value in (None, ""):
        return ""
    return format(_f(value), ".12g")


def _resource_identity(resource: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Identity guard for stale bases which predate canonical source dedupe.

    It only collapses rows with the same coded (or, if no code exists, named)
    resource, unit, consumption and explicit price. It does not infer or alter
    a norm's resource composition.
    """
    return resource_dedupe_key(resource)


def _dedupe_resources(resources: list[dict[str, Any]], *, normative_identity: Mapping[str, Any] | None = None) -> tuple[list[dict[str, Any]], int]:
    return dedupe_resources(resources, normative_identity=normative_identity)


def _base_type(prefix: Any, *, default: str = "ГЭСН") -> str:
    raw = str(prefix or "").strip().upper().replace(" ", "")
    if not raw:
        return default
    if raw.startswith("ГЭСН"):
        return "ГЭСН" + raw.replace("ГЭСН", "", 1).lower()
    if raw.startswith("ФЕР"):
        return "ФЕР" + raw.replace("ФЕР", "", 1).lower()
    if raw.startswith("ТЕР"):
        return "ТЕР" + raw.replace("ТЕР", "", 1).lower()
    return default


def _split_norm_ref(code: Any, *, default_base: str = "ГЭСН") -> tuple[str, str]:
    s = _norm_transport_text(code)
    prefix = _BASE_PREFIX_RE.match(s)
    base_type = _base_type(prefix.group(1) if prefix else "", default=default_base)
    bare = _BARE_NORM_RE.search(s)
    return base_type, bare.group(0) if bare else ""


def _has_explicit_base_prefix(code: Any) -> bool:
    return bool(_BASE_PREFIX_RE.match(_norm_transport_text(code)))


def _norm_code(code: Any) -> str:
    """Голый код нормы для обратной совместимости старых помощников."""
    return _split_norm_ref(code)[1]


def _norm_key(code: Any, *, base_type: Any = None) -> str:
    bt, bare = _split_norm_ref(code, default_base=str(base_type or "ГЭСН"))
    if base_type:
        bt = str(base_type).strip()
    return f"{bt}:{bare}" if bare else ""


def _display_code(bare_or_code: Any, base_type: Any) -> str:
    bt = str(base_type or "ГЭСН").strip() or "ГЭСН"
    bare = _norm_code(bare_or_code)
    if not bare:
        return str(bare_or_code or "")
    return f"{bt}{bare}" if bt.startswith(("ГЭСН", "ФЕР", "ТЕР")) else bare


def _work_steps(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, list):
        return [str(x).strip() for x in parsed if str(x).strip()]
    return [line.strip(" -\t") for line in text.splitlines() if line.strip(" -\t")]


def _default_base_paths() -> list[Path]:
    if DEFAULT_UNIFIED_BASE_PATH.exists():
        return [DEFAULT_UNIFIED_BASE_PATH]
    paths = [DEFAULT_BASE_PATH]
    if DEFAULT_BASE_V2_PATH.exists():
        paths.append(DEFAULT_BASE_V2_PATH)
    return paths


def _structured_base_path() -> Path:
    from proxy.smeta_core.base_registry import active_base

    return Path(active_base()["base_path"])


def _connect_structured_base_readonly(path: Path) -> sqlite3.Connection:
    from proxy.smeta_core.base_registry import runtime_data_path

    resolved = runtime_data_path(path)
    try:
        return readonly_revision_connection(resolved)
    except sqlite3.OperationalError as error:
        raise sqlite3.OperationalError(
            f"unable to open normative database {resolved}: {error}"
        ) from error


@lru_cache(maxsize=4)
def load_norms(path: str | None = None) -> dict[str, dict[str, Any]]:
    """Каталог норм из СЕМЕНИ (yaml) → {нормализованный_код: норма}. Кешируется."""
    import yaml

    p = Path(path) if path else DEFAULT_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: dict[str, dict[str, Any]] = {}
    for n in data.get("norms", []):
        code = n.get("code")
        if code:
            out[_norm_key(code)] = n
    return out


_retained_catalogs: OrderedDict[tuple[str, str, str, bool], dict[str, dict[str, Any]]] = OrderedDict()
_catalog_cache_lock = RLock()
_catalog_cache_hits = 0
_catalog_cache_misses = 0
_CatalogCacheInfo = namedtuple('CacheInfo', 'hits misses maxsize currsize')


def load_structured_base_norms(sqlite_path: str | None = None) -> dict[str, dict[str, Any]]:
    """Legacy public API returns an editable copy, never the source snapshot."""
    return deepcopy(_current_structured_catalog(sqlite_path))


def _current_structured_catalog(sqlite_path: str | None = None, *, code: str | None = None,
                                strict_family: bool = False) -> dict[str, dict[str, Any]]:
    global _catalog_cache_hits, _catalog_cache_misses
    from proxy.smeta_core.base_registry import runtime_data_path
    p = runtime_data_path(Path(sqlite_path) if sqlite_path else _structured_base_path()).resolve()
    if not p.exists():
        return {}
    # Current reads validate bytes under a SQLite read lock even on cache hits.
    # Explicit expected-identity reads can still use the retained immutable copy.
    conn = _connect_structured_base_readonly(p)
    try:
        key = (str(p), conn.base_sha256, _norm_transport_text(code) if code is not None else '', strict_family)
        with _catalog_cache_lock:
            norms = _retained_catalogs.get(key)
            if norms is None:
                _catalog_cache_misses += 1
            else:
                _catalog_cache_hits += 1
        if norms is None:
            norms = _load_structured_revision(str(p), conn, code=code, strict_family=strict_family)
    finally:
        conn.close()
    if norms:
        sha = next(iter(norms.values()))['normative_identity']['base_sha256']
        key = (str(p), sha, _norm_transport_text(code) if code is not None else '', strict_family)
        with _catalog_cache_lock:
            _retained_catalogs[key] = norms
            _retained_catalogs.move_to_end(key)
            while len({entry[:2] for entry in _retained_catalogs}) > 4:
                oldest_revision = next(iter(_retained_catalogs))[:2]
                for entry in list(_retained_catalogs):
                    if entry[:2] == oldest_revision:
                        del _retained_catalogs[entry]
    return norms


def _load_structured_revision(sqlite_path: str, conn: sqlite3.Connection, *, code: str | None = None,
                             strict_family: bool = False) -> dict[str, dict[str, Any]]:
    """Каталог норм из canonical SQLite → {код: норма}. {} если базы нет."""
    p = Path(sqlite_path) if sqlite_path else _structured_base_path()
    if not p.exists():
        return {}

    sha = conn.base_sha256
    conn.row_factory = sqlite3.Row
    where = ''
    params: tuple[str, ...] = ()
    if code is not None:
        if strict_family and not _has_explicit_base_prefix(code):
            where, params = ' WHERE bare_code=?', (_norm_code(code),)
        else:
            where, params = ' WHERE norm_key=?', (_norm_key(code),)
    norm_rows = conn.execute(
        """
        SELECT norm_key, norm_id, edition, source_doc, source_guid,
               display_code, base_type, norm_name, norm_unit, work_steps
        FROM norms
        """ + where + ' ORDER BY norm_key', params
    ).fetchall()
    if not norm_rows:
        return {}
    resources_by_key: dict[str, list[dict[str, Any]]] = {str(row["norm_key"]): [] for row in norm_rows}
    for row in conn.execute(
        """
        SELECT rowid AS row_id, norm_key, kind, resource_code, resource_name, resource_unit, per_unit, price
        FROM resources
        """ + (' WHERE norm_key IN (SELECT norm_key FROM norms' + where + ')' if where else '')
        + ' ORDER BY norm_key, id', params
    ):
        key = str(row["norm_key"])
        res = normalise_resource(dict(row))
        resources_by_key.setdefault(key, []).append(res)

    out: dict[str, dict[str, Any]] = {}
    for row in norm_rows:
        key = str(row["norm_key"])
        resources, duplicates_dropped = _dedupe_resources(resources_by_key.get(key, []), normative_identity=identity_for_row(row, sha))
        out[key] = {
            "normative_identity": identity_for_row(row, sha),
            "code": row["display_code"],
            "base_type": row["base_type"],
            "key": key,
            "norm_id": row["norm_id"],
            "edition": row["edition"],
            "source_ref": f"{row['source_doc']}#guid={row['source_guid']}",
            "name": row["norm_name"] or "",
            "unit": row["norm_unit"] or "",
            "work_steps": _work_steps(row["work_steps"]),
            "resources": resources,
            "_resource_identity_duplicates_dropped": duplicates_dropped,
            "_source_kind": "structured_sqlite",
            "_source_path": str(p),
        }
    return out


def load_base_norms(parquet_path: str | None = None) -> dict[str, dict[str, Any]]:
    if parquet_path is None and _structured_base_path().exists():
        return load_structured_base_norms(str(_structured_base_path()))
    if parquet_path is not None and Path(parquet_path).suffix.lower() in {'.sqlite', '.db'}:
        return load_structured_base_norms(parquet_path)
    return _load_legacy_base_norms(parquet_path)


@lru_cache(maxsize=4)
def _load_legacy_base_norms(parquet_path: str | None = None) -> dict[str, dict[str, Any]]:
    """Каталог норм из canonical base/parquet → {код: норма}. {} если базы нет. Кешируется.

    Без явного пути сначала читается `data/smeta_base/les_smeta_base.sqlite`.
    Parquet остаётся source/debug fallback и обратной совместимостью тестов.
    """
    if parquet_path is None:
        structured = _structured_base_path()
        if structured.exists():
            return load_structured_base_norms(str(structured))
    elif Path(parquet_path).suffix.lower() in {".sqlite", ".db"}:
        return load_structured_base_norms(parquet_path)

    paths = [Path(parquet_path)] if parquet_path else _default_base_paths()
    paths = [p for p in paths if p.exists()]
    if not paths:
        return {}
    import pandas as pd

    out: dict[str, dict[str, Any]] = {}
    for p in paths:
        df = pd.read_parquet(p)
        legacy_untyped = "base_type" not in df.columns and "norm_key" not in df.columns
        df = df.astype(object).where(pd.notnull(df), None)
        local: dict[str, dict[str, Any]] = {}
        for rec in df.to_dict(orient="records"):
            base_type = rec.get("base_type") or _split_norm_ref(rec.get("norm_code"))[0]
            code = rec.get("norm_code")
            key = rec.get("norm_key") or _norm_key(code, base_type=base_type)
            if not key:
                continue
            norm = local.get(key)
            if norm is None:
                norm = local[key] = {
                    "code": _display_code(code or key, base_type),
                    "base_type": base_type,
                    "key": key,
                    "name": rec.get("norm_name") or "",
                    "unit": rec.get("norm_unit") or "",
                    "work_steps": _work_steps(rec.get("work_steps")),
                    "resources": [],
                    "_source_kind": "legacy_untyped_parquet" if legacy_untyped else "base_parquet",
                    "_source_path": str(p),
                }
            elif not norm.get("work_steps"):
                norm["work_steps"] = _work_steps(rec.get("work_steps"))
            res: dict[str, Any] = {
                "kind": rec.get("kind"),
                "name": rec.get("resource_name") or "",
                "unit": rec.get("resource_unit") or "",
                "per_unit": rec.get("per_unit"),
            }
            if rec.get("resource_code"):
                res["code"] = rec["resource_code"]
            elif rec.get("kind") == "labor":                  # труд без кода → тарифный 1-100-NM по разряду
                tc = _labor_tariff_code(rec.get("resource_name"))
                if tc:
                    res["code"] = tc
            if rec.get("price") not in (None, ""):
                res["price"] = rec["price"]
            norm["resources"].append(res)
        for key, norm in local.items():
            norm["resources"], duplicates_dropped = _dedupe_resources(norm["resources"])
            norm["_resource_identity_duplicates_dropped"] = duplicates_dropped
            existing = out.get(key)
            if existing:
                for field in ("name", "unit"):
                    if not norm.get(field) and existing.get(field):
                        norm[field] = existing[field]
                if not norm.get("work_steps") and existing.get("work_steps"):
                    norm["work_steps"] = existing["work_steps"]
                if not norm.get("resources") and existing.get("resources"):
                    norm["resources"] = existing["resources"]
            out[key] = norm
    return out


def _clear_norm_catalogs() -> None:
    global _catalog_cache_hits, _catalog_cache_misses
    with _catalog_cache_lock:
        _catalog_cache_hits = _catalog_cache_misses = 0
        _retained_catalogs.clear()
    _load_legacy_base_norms.cache_clear()
    revision_sha256.cache_clear()


def _structured_catalog_cache_info():
    with _catalog_cache_lock:
        return _CatalogCacheInfo(_catalog_cache_hits, _catalog_cache_misses, 4,
                                len({entry[:2] for entry in _retained_catalogs}))


load_structured_base_norms.cache_clear = _clear_norm_catalogs
load_structured_base_norms.cache_info = _structured_catalog_cache_info
load_base_norms.cache_clear = _clear_norm_catalogs
load_base_norms.cache_info = _load_legacy_base_norms.cache_info


def _merged_norms(*, path: str | None = None, base_path: str | None = None,
                  code: str | None = None, strict_family: bool = False) -> dict[str, dict[str, Any]]:
    """Canonical SQLite is authoritative; demo seed is only a legacy fallback.

    A seed row carries its own resources and prices, so overlaying it changes
    the selected norm rather than just its display name. Never mix demo norms
    into an available versioned normative catalogue, even for missing codes.
    """
    if base_path is None and _structured_base_path().exists():
        return _current_structured_catalog(str(_structured_base_path()), code=code, strict_family=strict_family)
    elif base_path is not None and Path(base_path).suffix.lower() in {'.sqlite', '.db'}:
        return _current_structured_catalog(base_path, code=code, strict_family=strict_family)
    else:
        merged = load_base_norms(base_path)
    if any(norm.get("_source_kind") == "structured_sqlite" for norm in merged.values()):
        return merged
    merged = dict(merged)
    merged.update(load_norms(path))   # семя поверх базы
    return merged


def get_norm(
    code: str,
    *,
    path: str | None = None,
    base_path: str | None = None,
    strict_family: bool = False,
    expected_identity: Mapping[str, Any] | None = None,
) -> Optional[dict[str, Any]]:
    if expected_identity is not None:
        from proxy.smeta_core.base_registry import runtime_data_path
        resolved = runtime_data_path(Path(base_path) if base_path else _structured_base_path()).resolve()
        with _catalog_cache_lock:
            prefix = (str(resolved), str(expected_identity.get('base_sha256') or ''))
            retained = _retained_catalogs.get((*prefix, '', False))
            if retained is None:
                retained = _retained_catalogs.get((*prefix, _norm_transport_text(code), strict_family))
        if retained is not None:
            norm = _select_norm(retained, code, strict_family)
        else:
            norm = _select_norm(_merged_norms(path=path, base_path=base_path, code=code,
                                             strict_family=strict_family), code, strict_family)
        actual = (norm or {}).get('normative_identity') or {}
        if expected_identity.get('schema') != IDENTITY_SCHEMA or any(
            not expected_identity.get(field) or expected_identity.get(field) != actual.get(field) for field in IDENTITY_FIELDS
        ):
            raise NormRevisionConflict(expected_identity, actual, 'normative_identity_mismatch')
        return deepcopy(norm)
    norms = _merged_norms(path=path, base_path=base_path, code=code, strict_family=strict_family)
    return deepcopy(_select_norm(norms, code, strict_family))


def _select_norm(norms: dict[str, dict[str, Any]], code: str, strict_family: bool) -> Optional[dict[str, Any]]:
    key = _norm_key(code)
    if _has_explicit_base_prefix(code):
        return norms.get(key)
    bare = _norm_code(code)
    if bare and strict_family:
        matches = [norm for norm_key, norm in norms.items() if str(norm_key).endswith(f":{bare}")]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None
    return norms.get(key)


def list_norms(path: str | None = None, *, base_path: str | None = None) -> list[dict[str, Any]]:
    return [{"code": n["code"], "name": n.get("name", ""), "unit": n.get("unit", ""),
             "resources": len(n.get("resources", []))}
            for n in _merged_norms(path=path, base_path=base_path).values()]


def expand_position(
    code: str, qty: float, *, path: str | None = None, base_path: str | None = None
) -> Optional[list[dict[str, Any]]]:
    """Норма + объём → строки ресурсов (qty = per_unit × объём). None — норма не найдена."""
    norm = get_norm(code, path=path, base_path=base_path)
    if norm is None:
        return None
    q = _f(qty)
    lines: list[dict[str, Any]] = []
    for r in norm.get("resources", []):
        line: dict[str, Any] = {
            "kind": r.get("kind"),
            "name": r.get("name", ""),
            "unit": r.get("unit", ""),
            "qty": round(_f(r.get("per_unit")) * q, 6),
        }
        if r.get("code"):
            line["code"] = r["code"]
        if r.get("price") not in (None, ""):
            line["price"] = _f(r["price"])
        lines.append(line)
    return lines
