"""НР/СП по виду работ: норма ГЭСН → нормативы накладных расходов и сметной прибыли (% от ФОТ).

Норма даёт расход ресурсов, но НР (Приказ 812/пр) и СП (774/пр) присваиваются по ВИДУ РАБОТ —
их в норме нет. Этот сервис сопоставляет норму (по базе/сборнику шифра и ключевым словам
наименования) → НР%/СП%.
0 LLM. Каталог — редактируемый `config/domain/nr_sp.yaml` (семя + дефолт; полная таблица из Приказов).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Optional

DEFAULT_PATH = Path("config/domain/nr_sp.yaml")


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return d


def _code_norm(v: Any) -> str:
    return str(v or "").strip().lower().replace(" ", "")


def _collection_key(code: Any) -> str:
    """Return normalized norm collection key."""
    cd = _code_norm(code).replace(":", "")
    m = re.match(r"^(гэснм|гэсн)(\d{1,2})", cd)
    if m:
        base, number = m.groups()
        return f"{base}:{int(number):02d}"
    m = re.match(r"^(\d{1,2})(?:-|$)", cd)
    if not m:
        return ""
    base, number = "гэсн", m.group(1)
    return f"{base}:{int(number):02d}"


def _collection_norm(v: Any) -> str:
    s = _code_norm(v)
    if ":" not in s:
        return _collection_key(s)
    base, _, number = s.partition(":")
    if not base or not number.isdigit():
        return ""
    return f"{base}:{int(number):02d}"


def _result(w: dict[str, Any], *, default: bool = False) -> dict[str, Any]:
    return {
        "nr_pct": _f(w.get("nr_pct")),
        "sp_pct": _f(w.get("sp_pct")),
        "label": w.get("label", ""),
        "basis": w.get("basis", ""),
        "default": default,
    }


@lru_cache(maxsize=4)
def _load(path: str | None = None) -> dict[str, Any]:
    import yaml

    p = Path(path) if path else DEFAULT_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def resolve(name: str = "", *, code: str | None = None, path: str | None = None) -> dict[str, Any]:
    """Вид работ по шифру/наименованию нормы → {nr_pct, sp_pct, label, default}."""
    cfg = _load(path)
    collection = _collection_key(code)
    nm = (name or "").lower()
    if collection:
        for w in cfg.get("works", []) or []:
            if not w.get("collection_match_priority"):
                continue
            if not any(collection == _collection_norm(k) for k in (w.get("collections") or [])):
                continue
            if any(str(k).lower() in nm for k in (w.get("match") or [])):
                return _result(w)

        for w in cfg.get("works", []) or []:
            if any(collection == _collection_norm(k) for k in (w.get("collections") or [])):
                return _result(w)

    for w in cfg.get("works", []) or []:
        if any(str(k).lower() in nm for k in (w.get("match") or [])):
            return _result(w)
    d = cfg.get("default", {})
    return {"nr_pct": _f(d.get("nr_pct")), "sp_pct": _f(d.get("sp_pct")),
            "label": d.get("label", "по умолчанию"), "basis": "", "default": True}


def machinist_rate(*, path: str | None = None) -> float:
    """Ставка ОТм машинистов по умолчанию (руб/чел-ч), 0 = не подставлять."""
    return _f(_load(path).get("machinist_rate_default"), 0.0)
