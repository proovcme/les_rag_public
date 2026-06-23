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

# Префикс базы перед шифром: «ГЭСН 12-01-034-02» ≡ «12-01-034-02» (API smetnoedelo даёт без префикса,
# семя/чат — с «ГЭСН»). Снимаем, чтобы обе формы вели к одной норме.
_BASE_PREFIX_RE = re.compile(r"^(ГЭСН[РМПMR]*|ФЕР[РМПMR]*|ТЕР[РМПMR]*)", re.I)


def _f(value: Any) -> float:
    try:
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _norm_code(code: Any) -> str:
    s = str(code or "").strip().upper().replace(" ", "")
    return _BASE_PREFIX_RE.sub("", s)


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
            out[_norm_code(code)] = n
    return out


@lru_cache(maxsize=4)
def load_base_norms(parquet_path: str | None = None) -> dict[str, dict[str, Any]]:
    """Каталог норм из ПАРКЕТ-БАЗЫ → {код: норма}. {} если базы нет. Кешируется.

    Parquet — плоские строки-ресурсы (схема `tools.gesn_import.RESOURCE_FIELDS`),
    группируются по `norm_code` в норму вида {code, name, unit, resources:[…]} —
    тот же контракт, что у семени.
    """
    p = Path(parquet_path) if parquet_path else DEFAULT_BASE_PATH
    if not p.exists():
        return {}
    import pandas as pd

    df = pd.read_parquet(p)
    df = df.astype(object).where(pd.notnull(df), None)
    out: dict[str, dict[str, Any]] = {}
    for rec in df.to_dict(orient="records"):
        code = _norm_code(rec.get("norm_code"))
        if not code:
            continue
        norm = out.get(code)
        if norm is None:
            norm = out[code] = {
                "code": rec.get("norm_code") or code,
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
        if rec.get("price") not in (None, ""):
            res["price"] = rec["price"]
        norm["resources"].append(res)
    return out


def _merged_norms(*, path: str | None = None, base_path: str | None = None) -> dict[str, dict[str, Any]]:
    """База + семя в один каталог. Семя побеждает при совпадении кода (эталон точный)."""
    merged = dict(load_base_norms(base_path))
    merged.update(load_norms(path))   # семя поверх базы
    return merged


def get_norm(code: str, *, path: str | None = None, base_path: str | None = None) -> Optional[dict[str, Any]]:
    return _merged_norms(path=path, base_path=base_path).get(_norm_code(code))


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
