"""Тонкий end-to-end срез «дай смету на <объект>» (Ц16, капстоун).

Фраза → состав работ + ОБЪЁМЫ (параметрический шаблон) → существующий ЛСР-движок →
позиционная смета с итогом. 0 LLM по умолчанию (regex/словарь), детерминированно.

ADR-11 (числа из норм/шаблона, LLM ничего не считает):
  parse_request(text)  — regex/словарь: тип объекта, материал, этажность, площадь.
                          LLM-фолбэк ОПЦИОНАЛЕН (флаг use_llm), по умолчанию выключен.
  build_vor(tpl, prm)   — шаблон + параметры → позиции с ВЫЧИСЛЕННЫМИ объёмами (это ВОР).
                          Объёмы = eval(qty_formula) в безопасном неймспейсе {S,N,P,H,a,S1,…}.
  estimate(text)        — parse → выбрать шаблон → build_vor → lsr_assembly.assemble →
                          смета (позиции + итог + источники + допущения).

Геометрия (без чертежа): пятно квадратное, P = 4·sqrt(S/N). Допущения честно в шаблоне (ASSUME)
и в `assumptions` результата. Объёмы детерминированы → воспроизводимы в тесте.

ОГРАНИЧЕНИЕ: query-time БЕЗ сети — только локальная база норм (get_norm). Коды деревянного дома,
которых нет в локальной базе, помечаются в шаблоне TODO; смета собирается на доступных нормах.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Optional

DEFAULT_TEMPLATES_PATH = Path("config/domain/object_templates.yaml")

# Безопасный неймспейс для eval формул объёма (никаких builtins).
_FORMULA_NS = {"sqrt": math.sqrt, "min": min, "max": max, "round": round, "abs": abs}
# Разрешённые символы в формуле (буквы параметров + арифметика) — защита от инъекций в eval.
_FORMULA_RE = re.compile(r"^[\sA-Za-z0-9_.+\-*/()]+$")

_MATERIAL_WORDS = {
    "дерев": "дерево", "брус": "дерево", "бревен": "дерево", "бревён": "дерево",
    "деревян": "дерево", "сруб": "дерево",
    "кирпич": "кирпич", "бетон": "бетон", "монолит": "бетон", "каркас": "каркас",
    "газобетон": "газобетон", "пенобетон": "пенобетон", "блок": "блок",
}
_OBJECT_WORDS = ("дом", "коттедж", "дача", "здание", "сруб", "баня", "гараж")

# Этажность словом: одно/двух/трёх… → N.
_FLOORS_WORD = {
    "одноэтаж": 1, "однаэтаж": 1, "двухэтаж": 2, "двуэтаж": 2, "трёхэтаж": 3,
    "трехэтаж": 3, "четырёхэтаж": 4, "четырехэтаж": 4, "пятиэтаж": 5,
    "одноэтажн": 1, "двухэтажн": 2, "трёхэтажн": 3, "трехэтажн": 3,
}


def _f(v: Any) -> float:
    try:
        return float(str(v).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def load_templates(path: str | None = None) -> list[dict[str, Any]]:
    """Шаблоны объектов из YAML → список. {} если файла нет."""
    import yaml

    p = Path(path) if path else DEFAULT_TEMPLATES_PATH
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data.get("templates", []) or []


# ── разбор фразы ───────────────────────────────────────────────────────────────────────

def parse_request(text: str, *, use_llm: bool = False) -> dict[str, Any]:
    """Фраза → {object, material, floors, area, raw}. Детерминированно (regex/словарь).

    use_llm=True — опциональный фолбэк (по умолчанию ВЫКЛ; ADR-11: LLM только парсит фразу,
    ничего не считает). Фолбэк зовётся лишь когда детерминированный разбор неполон.
    """
    q = " ".join(str(text or "").split())
    ql = q.lower().replace("ё", "е")

    material: Optional[str] = None
    for stem, label in _MATERIAL_WORDS.items():
        if stem.replace("ё", "е") in ql:
            material = label
            break

    obj: Optional[str] = next((w for w in _OBJECT_WORDS if w in ql), None)

    floors: Optional[int] = None
    for stem, n in _FLOORS_WORD.items():
        if stem.replace("ё", "е") in ql:
            floors = n
            break
    if floors is None:
        m = re.search(r"(\d+)\s*-?\s*этаж", ql)
        if m:
            floors = int(m.group(1))

    # площадь: «100 м²», «100 м2», «100 кв.м», «площадью 100 метров», «100 квадратов»
    area: Optional[float] = None
    m = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:м²|м2|м\s*кв|кв\.?\s*м|квадрат\w*|метр\w*)",
        ql,
    )
    if not m:
        m = re.search(r"площад\w*\D{0,8}(\d+(?:[.,]\d+)?)", ql)
    if m:
        area = _f(m.group(1))

    result = {
        "object": obj, "material": material, "floors": floors, "area": area, "raw": q,
        "source": "deterministic",
    }

    if use_llm and (material is None or area is None):
        llm = _parse_request_llm(q)
        if llm:
            for k in ("object", "material", "floors", "area"):
                if result.get(k) in (None, "") and llm.get(k) not in (None, ""):
                    result[k] = llm[k]
            result["source"] = "deterministic+llm"
    return result


def _parse_request_llm(text: str) -> Optional[dict[str, Any]]:
    """ОПЦ. LLM-фолбэк разбора (НЕ считает — только извлекает поля). Тихо None при сбое/офлайне."""
    try:  # импорт лениво — путь не обязателен и сеть недоверенная по умолчанию
        from proxy.services import mlx_client  # type: ignore
    except Exception:
        return None
    try:
        import json

        prompt = (
            "Извлеки из фразы поля строительного объекта строго как JSON "
            '{"object":str|null,"material":"дерево|кирпич|бетон|...|null",'
            '"floors":int|null,"area":number|null}. Только JSON, без пояснений.\n'
            f"Фраза: {text}"
        )
        raw = mlx_client.complete(prompt, max_tokens=120)  # type: ignore[attr-defined]
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


# ── выбор шаблона ──────────────────────────────────────────────────────────────────────

def select_template(parsed: dict[str, Any], *, path: str | None = None) -> Optional[dict[str, Any]]:
    """Параметры разбора → подходящий шаблон по match.object/match.material. None — нет матча."""
    obj = (parsed.get("object") or "").lower()
    mat = (parsed.get("material") or "").lower()
    raw = (parsed.get("raw") or "").lower().replace("ё", "е")
    for tpl in load_templates(path):
        match = tpl.get("match", {})
        obj_ok = any(o in raw or o == obj for o in match.get("object", [])) if match.get("object") else True
        # Материал-специфичный шаблон (есть match.material) ТРЕБУЕТ сигнал материала — слово в
        # запросе ИЛИ распознанный материал. Пустой mat НЕ матчит (иначе startswith("") == True
        # лепил «деревянный дом» на любой объект — офис/монолит и т.п.). Нет матча → к модели.
        materials = [m.replace("ё", "е") for m in match.get("material", [])]
        if materials:
            mat_ok = any(m in raw for m in materials) or (bool(mat) and any(m.startswith(mat) for m in materials))
        else:
            mat_ok = True
        if obj_ok and mat_ok:
            return tpl
    return None


# ── геометрия + объёмы (это ВОР) ─────────────────────────────────────────────────────────

def _geometry(area: float, floors: int, tpl: dict[str, Any]) -> dict[str, float]:
    """{S,N} + допущения шаблона → производные {S1,a,P,H,…}. Квадратное пятно: P=4·sqrt(S/N)."""
    S = max(_f(area), 0.0)
    N = max(int(floors or 1), 1)
    S1 = S / N if N else S
    a = math.sqrt(S1) if S1 > 0 else 0.0
    P = 4.0 * a
    ns: dict[str, float] = {"S": S, "N": float(N), "S1": S1, "a": a, "P": P}
    # геометрические константы шаблона (H, коэффициенты) — в неймспейс формул
    for k, v in (tpl.get("geometry") or {}).items():
        ns[k] = _f(v)
    return ns


def _eval_formula(formula: str, ns: dict[str, float]) -> float:
    """Безопасный eval арифметической формулы объёма в неймспейсе параметров."""
    expr = str(formula or "").strip()
    if not expr or not _FORMULA_RE.match(expr):
        raise ValueError(f"Недопустимая формула объёма: {formula!r}")
    env = {**_FORMULA_NS, **ns}
    return round(float(eval(expr, {"__builtins__": {}}, env)), 6)  # noqa: S307 — выражение валидируется


def build_vor(template: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Шаблон + параметры → ВОР: позиции с ВЫЧИСЛЕННЫМИ объёмами. 0 LLM, объёмы из формул."""
    ns = _geometry(_f(params.get("area")), int(params.get("floors") or 1), template)
    positions: list[dict[str, Any]] = []
    for p in template.get("positions", []):
        if not p.get("code") or not p.get("qty_formula"):  # TODO-позиции (нет нормы/формулы) — пропуск
            continue
        qty = _eval_formula(p["qty_formula"], ns)
        positions.append({
            "code": p["code"], "name": p.get("name", ""), "unit": p.get("unit", ""),
            "qty": qty, "work_kind": p.get("work_kind", ""), "formula": p["qty_formula"],
        })
    return {
        "template": template.get("id"),
        "params": {"S": ns["S"], "N": int(ns["N"]), "P": round(ns["P"], 4),
                   "S1": round(ns["S1"], 4)},
        "positions": positions,
    }


# ── сборка сметы (ВОР → ЛСР-движок) ──────────────────────────────────────────────────────

def estimate(
    text: str,
    *,
    use_llm: bool = False,
    condition: str | None = None,
    templates_path: str | None = None,
) -> dict[str, Any]:
    """Фраза → смета: parse → шаблон → ВОР → lsr_assembly.assemble. Локально, без сети.

    Возвращает {ok, parsed, template, vor, estimate, assumptions, error?}. ok=False — нет
    шаблона/площади/этажности (просим уточнить), смета не собирается.
    """
    from proxy.services.gesn_service import get_norm
    from proxy.services.lsr_assembly_service import assemble
    from proxy.services.nr_sp_service import resolve as resolve_nr_sp

    parsed = parse_request(text, use_llm=use_llm)

    if not parsed.get("area"):
        return {"ok": False, "parsed": parsed,
                "error": "Не распознана площадь — укажи «… площадью N м²»."}
    if not parsed.get("floors"):
        parsed = {**parsed, "floors": 1}  # этажность по умолчанию — 1 (явно фиксируем)

    tpl = select_template(parsed, path=templates_path)
    if tpl is None:
        return {"ok": False, "parsed": parsed,
                "error": "Нет шаблона под объект/материал (есть: деревянный дом)."}

    vor = build_vor(tpl, parsed)

    # ВОР → позиции движка: НР/СП по виду работ (из work_kind), пометка отсутствующих норм.
    positions: list[dict[str, Any]] = []
    missing_codes: list[str] = []
    for v in vor["positions"]:
        norm = get_norm(v["code"])  # ЛОКАЛЬНО, без сети
        if norm is None:
            missing_codes.append(v["code"])  # честно: нормы нет → в смету не идёт
            continue
        rs = resolve_nr_sp(v.get("work_kind") or norm.get("name", ""))
        positions.append({
            "code": v["code"], "name": v["name"], "unit": v["unit"], "qty": v["qty"],
            "section": v.get("work_kind", "") or "Конструктив",
            "nr_pct": rs["nr_pct"], "sp_pct": rs["sp_pct"],
        })

    lsr = assemble(positions, condition=condition) if positions else {
        "positions": [], "summary": {"positions": 0, "total": 0.0, "base_total": 0.0,
                                     "flags": [], "needs_price": 0}}

    # Хвост сметы: ИТОГО СМР (прямые+НР+СП) → непредвиденные → НДС → ВСЕГО («общая цена»).
    # Проценты — стандартные укрупнённые (МДС/НК РФ): непредвиденные ~2%, НДС 20%.
    smr = round(_f(lsr.get("summary", {}).get("total")), 2)
    cont_pct, vat_pct = 2.0, 20.0
    contingency = round(smr * cont_pct / 100, 2)
    before_vat = round(smr + contingency, 2)
    vat = round(before_vat * vat_pct / 100, 2)
    grand_total = round(before_vat + vat, 2)
    totals = {
        "smr": smr, "contingency_pct": cont_pct, "contingency": contingency,
        "before_vat": before_vat, "vat_pct": vat_pct, "vat": vat, "grand_total": grand_total,
        "positions": len(positions),
    }

    assumptions = _collect_assumptions(tpl, vor["params"], missing_codes)
    return {
        "ok": True,
        "parsed": parsed,
        "template": {"id": tpl.get("id"), "name": tpl.get("name")},
        "vor": vor,
        "estimate": lsr,
        "totals": totals,
        "missing_codes": missing_codes,
        "assumptions": assumptions,
    }


def _collect_assumptions(
    tpl: dict[str, Any], params: dict[str, Any], missing: list[str]
) -> list[str]:
    """Человекочитаемые допущения (геометрия/коэффициенты/пропуски) для прозрачности сметы."""
    geo = tpl.get("geometry") or {}
    out = [
        f"Пятно квадратное: периметр P = 4·√(S/N) = {params.get('P')} м "
        f"(S={params.get('S')} м², N={params.get('N')}, S₁={params.get('S1')} м²).",
        f"Высота этажа H = {geo.get('H', '?')} м (ASSUME).",
        f"Коэф. скатной кровли = {geo.get('roof_slope_k', '?')} к площади застройки (ASSUME).",
        f"Сечение ленты фундамента = {geo.get('found_section', '?')} м² (ASSUME).",
        "Объёмы — из формул шаблона над {S,N,P,H,S₁}; числа из норм ГЭСН (ADR-11, 0 LLM в расчёте).",
    ]
    if missing:
        out.append(f"Нет нормы в локальной базе (пропущены): {', '.join(missing)}.")
    return out
