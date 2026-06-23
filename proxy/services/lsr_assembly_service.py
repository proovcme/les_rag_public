"""Движок сборки ЛСР: позиция (объём + ресурсы) → цены → стеснённость → НР/СП → Всего.

Связывает кирпичи сметного ценообразования в сборку позиция-к-позиции (0 LLM, ADR-11):
  объём (ВОР) → ресурсы позиции → цены (ФГИС ЦС lookup / КАЦ для неучтённых) →
  ОЗП/ЭМ(вкл. ЗПМ)/М → коэф. стеснённости → НР/СП → Всего по позиции → свод в ЛСР.

Бухгалтерия позиции выверена на `Эталон_кровля` (медный отлив, поз.1):
  прямые = ОЗП + ЭМ(машины+ОТм) + М; ФОТ = ОЗП + ЗПМ; НР=ФОТ·нр%; СП=ФОТ·сп%; Всего=прямые+НР+СП.

Чего движок НЕ делает сам: разложение нормы ГЭСН на ресурсы (нужна база ГЭСН-2022, не загружена) —
ресурсы приходят на вход (как их выдала бы ГЭСН). Это следующий стык, как импорт ФГИС ЦС.

Виды ресурсов (`kind`): labor (рабочие→ОЗП) · machinist (ОТм→ЗПМ, в ЭМ) · machine (машины→ЭМ) ·
material (→М). Цена строки: явная `price`, иначе `code`→ФГИС ЦС, иначе material→КАЦ по наименованию.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from proxy.services import stesnennost_service as st


def _f(value: Any) -> float:
    try:
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _norm_name(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower().replace("ё", "е")).strip(" .,;:")


def _resolve_book(book: str | None):
    """Имя книги цен → PriceBook | None (для lookup по коду)."""
    from proxy.services import fgis_price_service as fps

    books = fps.available_pricebooks()
    if not books:
        return None
    path = next((p for p in books if Path(p).stem == book), None) if book else books[0]
    return fps.get_pricebook(path) if path else None


def _resource_price(
    res: dict[str, Any], pricebook, kac_map: dict[str, float]
) -> tuple[Optional[float], str]:
    """Цена единицы ресурса + источник. (price, source) | (None, 'missing')."""
    if res.get("price") not in (None, ""):
        return _f(res.get("price")), "manual"
    code = str(res.get("code") or "").strip()
    if code and pricebook is not None:
        rec = pricebook.lookup(code)
        if rec is not None:
            return _f(rec.get("price_current_eff")), "fgis"
    if str(res.get("kind")) == "material" and kac_map:
        p = kac_map.get(_norm_name(res.get("name")))
        if p is not None:
            return _f(p), "kac"
    return None, "missing"


def compute_position(
    position: dict[str, Any],
    *,
    pricebook=None,
    kac_map: dict[str, float] | None = None,
    k_ozp: float = 1.0,
    k_em: float = 1.0,
) -> dict[str, Any]:
    """Одна позиция: ресурсы → цены → ОЗП/ЭМ/ЗПМ/М → стеснённость → НР/СП → Всего."""
    kac_map = kac_map or {}
    ozp = zpm = machine_only = mat = 0.0
    priced: list[dict[str, Any]] = []
    flags: list[str] = []

    # Норма ГЭСН → ресурсы: если ресурсы не заданы, но есть код — разворачиваем по норме.
    resources = position.get("resources") or []
    if not resources and position.get("code"):
        from proxy.services import gesn_service

        expanded = gesn_service.expand_position(position["code"], _f(position.get("qty")))
        if expanded is None:
            flags.append(f"норма ГЭСН не найдена: {position.get('code')}")
        else:
            resources = expanded

    for res in resources:
        kind = str(res.get("kind") or "")
        qty = _f(res.get("qty"))
        price, src = _resource_price(res, pricebook, kac_map)
        if price is None:
            flags.append(f"нет цены: {res.get('name','?')} ({res.get('code','—')})")
            cost = 0.0
        else:
            cost = round(qty * price, 2)
        if kind == "labor":
            ozp += cost
        elif kind == "machinist":
            zpm += cost
        elif kind == "machine":
            machine_only += cost
        elif kind == "material":
            mat += cost
        else:
            flags.append(f"неизвестный вид ресурса: {kind!r}")
        priced.append({**res, "price_used": price, "price_source": src, "cost": cost})

    em = round(machine_only + zpm, 2)
    pos_in = {
        "ozp": round(ozp, 2), "em": em, "zpm": round(zpm, 2), "mat": round(mat, 2),
        "nr_pct": _f(position.get("nr_pct")), "sp_pct": _f(position.get("sp_pct")),
    }
    res = st.apply_position(pos_in, k_ozp=k_ozp, k_em=k_em)
    chosen = res["adjusted"] if (k_ozp != 1.0 or k_em != 1.0) else res["base"]
    return {
        "code": position.get("code", ""),
        "name": position.get("name", ""),
        "unit": position.get("unit", ""),
        "qty": _f(position.get("qty")),
        "section": position.get("section", "") or "Без раздела",
        "resources": priced,
        "k_ozp": k_ozp, "k_em": k_em,
        "base": res["base"],
        "adjusted": res["adjusted"],
        "total": chosen["total"],
        "uplift": res["uplift"],
        "flags": flags,
    }


def assemble(
    positions: list[dict[str, Any]],
    *,
    book: str | None = None,
    kac_prices: dict[str, float] | None = None,
    condition: str | None = None,
    k_ozp: float | None = None,
    k_em: float | None = None,
) -> dict[str, Any]:
    """Собрать ЛСР из позиций. Цены — ФГИС ЦС (book) / КАЦ (kac_prices) / явные. Стеснённость — опц."""
    if condition:
        cond = st.get_condition(condition)
        if cond is None:
            raise ValueError(f"Условие стеснённости {condition!r} не найдено")
        k_ozp = _f(cond["k_ozp"]) if k_ozp is None else k_ozp
        k_em = _f(cond["k_em"]) if k_em is None else k_em
    k_ozp = 1.0 if k_ozp is None else k_ozp
    k_em = 1.0 if k_em is None else k_em

    pricebook = _resolve_book(book) if book is not None else _resolve_book(None)
    kac_map = {_norm_name(k): _f(v) for k, v in (kac_prices or {}).items()}

    computed = [
        compute_position(p, pricebook=pricebook, kac_map=kac_map, k_ozp=k_ozp, k_em=k_em)
        for p in (positions or [])
    ]

    sections: dict[str, dict[str, Any]] = {}
    for c in computed:
        s = sections.setdefault(c["section"], {"section": c["section"], "positions": 0, "total": 0.0})
        s["positions"] += 1
        s["total"] = round(s["total"] + c["total"], 2)

    base_total = round(sum(c["base"]["total"] for c in computed), 2)
    total = round(sum(c["total"] for c in computed), 2)
    flags = [f for c in computed for f in c["flags"]]
    return {
        "k_ozp": k_ozp, "k_em": k_em, "condition": condition,
        "positions": computed,
        "sections": list(sections.values()),
        "summary": {
            "positions": len(computed),
            "base_total": base_total,
            "total": total,
            "stesnennost_uplift": round(total - base_total, 2),
            "flags": flags,
            "needs_price": len(flags),
        },
    }
