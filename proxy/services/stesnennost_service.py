"""Коэффициент стеснённости (усложняющих условий) → пересчёт позиции ЛСР.

Регламент (Пояснительная записка / Методика 421/пр): при стеснённых/усложняющих условиях к
**ОЗП** (оплата труда рабочих) и **ЭМ** (эксплуатация машин, включая ЗПМ) применяется повышающий
коэффициент; материалы не затрагиваются. Это меняет ФОТ → НР → СП → Всего по позиции.

0 LLM: каталог коэффициентов — редактируемый `config/domain/stesnennost.yaml` (знание ≠ веса,
см. [[smeta-ontology]] концепт coef_stesn), расчёт — детерминированная арифметика (ADR-11).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

DEFAULT_PATH = Path("config/domain/stesnennost.yaml")


def _f(value: Any) -> float:
    try:
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


@lru_cache(maxsize=4)
def load_conditions(path: str | None = None) -> dict[str, dict[str, Any]]:
    """Каталог условий → {id: {label, k_ozp, k_em, basis}}. Кешируется."""
    import yaml

    p = Path(path) if path else DEFAULT_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {c["id"]: c for c in data.get("conditions", []) if c.get("id")}


def list_conditions(path: str | None = None) -> list[dict[str, Any]]:
    return list(load_conditions(path).values())


def get_condition(key: str, *, path: str | None = None) -> Optional[dict[str, Any]]:
    """Условие по id или (без учёта регистра) по label."""
    cat = load_conditions(path)
    if key in cat:
        return cat[key]
    kl = str(key or "").strip().casefold()
    for c in cat.values():
        if str(c.get("label", "")).casefold() == kl:
            return c
    return None


def _calc(ozp: float, em: float, zpm: float, mat: float, nr_pct: float, sp_pct: float) -> dict[str, float]:
    """Прямые → ФОТ → НР → СП → Всего по позиции (числа считает код)."""
    direct = round(ozp + em + mat, 2)
    fot = round(ozp + zpm, 2)              # ФОТ = ОЗП рабочих + ЗПМ машинистов
    nr = round(fot * nr_pct / 100, 2)
    sp = round(fot * sp_pct / 100, 2)
    total = round(direct + nr + sp, 2)
    return {"ozp": round(ozp, 2), "em": round(em, 2), "zpm": round(zpm, 2), "mat": round(mat, 2),
            "direct": direct, "fot": fot, "nr": nr, "sp": sp, "total": total}


def apply_position(position: dict[str, Any], *, k_ozp: float, k_em: float) -> dict[str, Any]:
    """Применить коэффициенты к ОЗП и ЭМ позиции. Возвращает base/adjusted/uplift."""
    ozp, em = _f(position.get("ozp")), _f(position.get("em"))
    zpm, mat = _f(position.get("zpm")), _f(position.get("mat"))
    nr_pct, sp_pct = _f(position.get("nr_pct")), _f(position.get("sp_pct"))

    base = _calc(ozp, em, zpm, mat, nr_pct, sp_pct)
    adj = _calc(ozp * k_ozp, em * k_em, zpm * k_em, mat, nr_pct, sp_pct)
    return {
        "name": position.get("name", ""),
        "k_ozp": k_ozp,
        "k_em": k_em,
        "base": base,
        "adjusted": adj,
        "uplift": round(adj["total"] - base["total"], 2),
    }


def apply(
    positions: list[dict[str, Any]],
    *,
    condition: str | None = None,
    k_ozp: float | None = None,
    k_em: float | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """Применить стеснённость к позициям по условию из каталога ИЛИ явным k_ozp/k_em."""
    cond = None
    if condition:
        cond = get_condition(condition, path=path)
        if cond is None:
            raise ValueError(f"Условие {condition!r} не найдено")
        k_ozp = _f(cond["k_ozp"]) if k_ozp is None else k_ozp
        k_em = _f(cond["k_em"]) if k_em is None else k_em
    if k_ozp is None or k_em is None:
        raise ValueError("Нужно condition или явные k_ozp и k_em")

    rows = [apply_position(p, k_ozp=k_ozp, k_em=k_em) for p in (positions or [])]
    base_total = round(sum(r["base"]["total"] for r in rows), 2)
    adj_total = round(sum(r["adjusted"]["total"] for r in rows), 2)
    return {
        "condition": (cond["id"] if cond else None),
        "condition_label": (cond["label"] if cond else None),
        "k_ozp": k_ozp,
        "k_em": k_em,
        "positions": rows,
        "summary": {
            "positions": len(rows),
            "base_total": base_total,
            "adjusted_total": adj_total,
            "uplift": round(adj_total - base_total, 2),
        },
    }
