"""ГЭСН: норма → ресурсы (расход труда/машин/материалов на единицу) → строки для сборки ЛСР.

Замыкает конвейер ценообразования: позиция {код ГЭСН, объём} → ресурсы (через норму) → дальше
их пайплайн lsr_assembly (цены ФГИС ЦС/КАЦ → ОЗП/ЭМ/М → стеснённость → НР/СП → Всего). 0 LLM.

Норма даёт КОЛИЧЕСТВА на единицу; `expand_position(code, qty)` умножает на объём позиции →
строки ресурсов (kind/name/code/qty[/price]). Цены машин/материалов резолвятся по code из ФГИС ЦС
в сборке (если в норме нет снимка price); ОЗП/ОТм идут тарифом (price).

Два источника норм (объединяются прозрачно):
- **Семя** `config/domain/gesn_seed.yaml` — демо-норма эталона (выверена под gold-тест).
- **База** `data/gesn_base/gesn2022.parquet` — полная ГЭСН-2022 (десятки тысяч норм),
  импортируется `tools/gesn_import.py` (как ФГИС ЦС). Если базы нет — работаем на семени.
  При совпадении кода **семя побеждает** (эталон остаётся точным).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

DEFAULT_PATH = Path("config/domain/gesn_seed.yaml")
DEFAULT_BASE_PATH = Path("data/gesn_base/gesn2022.parquet")
DEFAULT_BASE_V2_PATH = Path("data/gesn_base/gesn2022_v2.parquet")

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


def _f(value: Any) -> float:
    try:
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


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
    s = str(code or "").strip().upper().replace(" ", "")
    prefix = _BASE_PREFIX_RE.match(s)
    base_type = _base_type(prefix.group(1) if prefix else "", default=default_base)
    bare = _BARE_NORM_RE.search(s)
    return base_type, bare.group(0) if bare else ""


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


def _default_base_paths() -> list[Path]:
    paths = [DEFAULT_BASE_PATH]
    if DEFAULT_BASE_V2_PATH.exists():
        paths.append(DEFAULT_BASE_V2_PATH)
    return paths


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
def load_base_norms(parquet_path: str | None = None) -> dict[str, dict[str, Any]]:
    """Каталог норм из ПАРКЕТ-БАЗЫ → {код: норма}. {} если базы нет. Кешируется.

    Parquet — плоские строки-ресурсы (схема `tools.gesn_import.RESOURCE_FIELDS`),
    группируются по `norm_code` в норму вида {code, name, unit, resources:[…]} —
    тот же контракт, что у семени.
    """
    paths = [Path(parquet_path)] if parquet_path else _default_base_paths()
    paths = [p for p in paths if p.exists()]
    if not paths:
        return {}
    import pandas as pd

    out: dict[str, dict[str, Any]] = {}
    for p in paths:
        df = pd.read_parquet(p)
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
                    "resources": [],
                }
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
        out.update(local)
    return out


def _merged_norms(*, path: str | None = None, base_path: str | None = None) -> dict[str, dict[str, Any]]:
    """База + семя в один каталог. Семя побеждает при совпадении кода (эталон точный)."""
    merged = dict(load_base_norms(base_path))
    merged.update(load_norms(path))   # семя поверх базы
    return merged


def get_norm(code: str, *, path: str | None = None, base_path: str | None = None) -> Optional[dict[str, Any]]:
    return _merged_norms(path=path, base_path=base_path).get(_norm_key(code))


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
