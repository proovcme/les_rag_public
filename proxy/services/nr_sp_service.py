"""НР/СП по виду работ: норма ГЭСН → нормативы накладных расходов и сметной прибыли (% от ФОТ).

Норма даёт расход ресурсов, но НР (Приказ 812/пр) и СП (774/пр) присваиваются по ВИДУ РАБОТ —
их в норме нет. Этот сервис сопоставляет норму (по ключевым словам наименования) → НР%/СП%.
0 LLM. Каталог — редактируемый `config/domain/nr_sp.yaml` (семя + дефолт; полная таблица из Приказов).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

DEFAULT_PATH = Path("config/domain/nr_sp.yaml")


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return d


@lru_cache(maxsize=4)
def _load(path: str | None = None) -> dict[str, Any]:
    import yaml

    p = Path(path) if path else DEFAULT_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def resolve(name: str = "", *, path: str | None = None) -> dict[str, Any]:
    """Вид работ по наименованию нормы → {nr_pct, sp_pct, label, default}. Дефолт если не распознан."""
    cfg = _load(path)
    nm = (name or "").lower()
    for w in cfg.get("works", []) or []:
        if any(str(k).lower() in nm for k in (w.get("match") or [])):
            return {"nr_pct": _f(w.get("nr_pct")), "sp_pct": _f(w.get("sp_pct")),
                    "label": w.get("label", ""), "basis": w.get("basis", ""), "default": False}
    d = cfg.get("default", {})
    return {"nr_pct": _f(d.get("nr_pct")), "sp_pct": _f(d.get("sp_pct")),
            "label": d.get("label", "по умолчанию"), "basis": "", "default": True}


def machinist_rate(*, path: str | None = None) -> float:
    """Ставка ОТм машинистов по умолчанию (руб/чел-ч), 0 = не подставлять."""
    return _f(_load(path).get("machinist_rate_default"), 0.0)
