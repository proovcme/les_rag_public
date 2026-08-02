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
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

DEFAULT_PATH = Path("config/domain/gesn_seed.yaml")
DEFAULT_BASE_PATH = Path("data/gesn_base/gesn2022.parquet")
DEFAULT_BASE_V2_PATH = Path("data/gesn_base/gesn2022_v2.parquet")
DEFAULT_UNIFIED_BASE_PATH = Path("data/gesn_base/gesn2022_unified.parquet")
DEFAULT_STRUCTURED_BASE_PATH = Path("data/smeta_base/les_smeta_base.sqlite")

# Старые базы могли хранить труд как «Средний разряд работы N,M» без кода.
# Выводим тарифный код 1-100-NM (эталон: разряд 2,5 → 1-100-25) как fallback; новый FGIS-парсер
# сохраняет тариф сразу. Машинист-агрегат без разряда → код не выводим (флаг «нет цены»).
_LABOR_RAZRYAD_RE = re.compile(r"разряд\D*(\d)[.,](\d)")


def _labor_tariff_code(name: Any) -> Optional[str]:
    m = _LABOR_RAZRYAD_RE.search(str(name or "").lower())
    return f"1-100-{m.group(1)}{m.group(2)}" if m else None

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
    code = _resource_text_key(resource.get("code"))
    name = _resource_text_key(resource.get("name"))
    return (
        _resource_text_key(resource.get("kind")),
        "code" if code else "name",
        code or name,
        _resource_text_key(resource.get("unit")),
        f"{_resource_number_key(resource.get('per_unit'))}|{_resource_number_key(resource.get('price'))}",
    )


def _dedupe_resources(resources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen: set[tuple[str, str, str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for resource in resources:
        identity = _resource_identity(resource)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(resource)
    return unique, len(resources) - len(unique)


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
        return sqlite3.connect(
            f"{resolved.as_uri()}?mode=ro&immutable=1",
            uri=True,
            timeout=30.0,
        )
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


@lru_cache(maxsize=4)
def load_structured_base_norms(sqlite_path: str | None = None) -> dict[str, dict[str, Any]]:
    """Каталог норм из canonical SQLite → {код: норма}. {} если базы нет."""
    p = Path(sqlite_path) if sqlite_path else _structured_base_path()
    if not p.exists():
        return {}

    conn = _connect_structured_base_readonly(p)
    conn.row_factory = sqlite3.Row
    try:
        norm_rows = conn.execute(
            """
            SELECT norm_key, display_code, base_type, norm_name, norm_unit, work_steps
            FROM norms
            ORDER BY norm_key
            """
        ).fetchall()
        if not norm_rows:
            return {}
        resources_by_key: dict[str, list[dict[str, Any]]] = {str(row["norm_key"]): [] for row in norm_rows}
        for row in conn.execute(
            """
            SELECT norm_key, kind, resource_code, resource_name, resource_unit, per_unit, price
            FROM resources
            ORDER BY norm_key, id
            """
        ):
            key = str(row["norm_key"])
            res: dict[str, Any] = {
                "kind": row["kind"],
                "name": row["resource_name"] or "",
                "unit": row["resource_unit"] or "",
                "per_unit": row["per_unit"],
            }
            if row["resource_code"]:
                res["code"] = row["resource_code"]
            elif row["kind"] == "labor":
                tc = _labor_tariff_code(row["resource_name"])
                if tc:
                    res["code"] = tc
            if row["price"] not in (None, ""):
                res["price"] = row["price"]
            resources_by_key.setdefault(key, []).append(res)
    finally:
        conn.close()

    out: dict[str, dict[str, Any]] = {}
    for row in norm_rows:
        key = str(row["norm_key"])
        resources, duplicates_dropped = _dedupe_resources(resources_by_key.get(key, []))
        out[key] = {
            "code": row["display_code"],
            "base_type": row["base_type"],
            "key": key,
            "name": row["norm_name"] or "",
            "unit": row["norm_unit"] or "",
            "work_steps": _work_steps(row["work_steps"]),
            "resources": resources,
            "_resource_identity_duplicates_dropped": duplicates_dropped,
            "_source_kind": "structured_sqlite",
            "_source_path": str(p),
        }
    return out


@lru_cache(maxsize=4)
def load_base_norms(parquet_path: str | None = None) -> dict[str, dict[str, Any]]:
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


def _merged_norms(*, path: str | None = None, base_path: str | None = None) -> dict[str, dict[str, Any]]:
    """База + семя в один каталог. Семя побеждает при совпадении кода (эталон точный)."""
    merged = dict(load_base_norms(base_path))
    merged.update(load_norms(path))   # семя поверх базы
    return merged


def get_norm(
    code: str,
    *,
    path: str | None = None,
    base_path: str | None = None,
    strict_family: bool = False,
) -> Optional[dict[str, Any]]:
    norms = _merged_norms(path=path, base_path=base_path)
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
