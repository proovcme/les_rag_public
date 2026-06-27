"""Тонкий end-to-end срез «дай смету на <объект>» (Ц16, капстоун).

Фраза → состав работ + ОБЪЁМЫ (параметрический шаблон) → существующий ЛСР-движок →
прикидка стоимости объекта. 0 LLM по умолчанию (regex/словарь), детерминированно.

ADR-11 (числа из норм/шаблона, LLM ничего не считает):
  parse_request(text)  — regex/словарь: тип объекта, материал, этажность, площадь.
                          LLM-фолбэк ОПЦИОНАЛЕН (флаг use_llm), по умолчанию выключен.
  build_vor(tpl, prm)   — шаблон + параметры → позиции с ВЫЧИСЛЕННЫМИ объёмами (это ВОР).
                          Объёмы = eval(qty_formula) в безопасном неймспейсе {S,N,P,H,a,S1,…}.
  estimate(text)        — parse → выбрать шаблон → build_vor → lsr_assembly.assemble →
                          ГЭСН-конструктив + ASSUME-разделы + хвост НДС.

Геометрия (без чертежа): пятно квадратное, P = 4·sqrt(S/N). Допущения честно в шаблоне (ASSUME)
и в `assumptions` результата. Объёмы детерминированы → воспроизводимы в тесте.

ОГРАНИЧЕНИЕ: query-time БЕЗ сети — только локальная база норм (get_norm). Коды деревянного дома,
которых нет в локальной базе, помечаются в шаблоне TODO; прикидка собирается на доступных нормах.
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
_FORMULA_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_UNIT_FACTOR_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(.+)$")

_MATERIAL_WORDS = {
    "дерев": "дерево", "брус": "дерево", "бревен": "дерево", "бревён": "дерево",
    "деревян": "дерево", "сруб": "дерево",
    "кирпич": "кирпич", "бетон": "бетон", "монолит": "бетон", "каркас": "каркас",
    "газобетон": "газобетон", "пенобетон": "пенобетон", "блок": "блок",
}
_OBJECT_WORDS = ("дом", "коттедж", "дача", "здание", "сруб", "баня", "гараж")
_HOUSE_OBJECT_WORDS = {"дом", "коттедж", "дача", "сруб"}
_MATERIAL_ANALOGS = {
    # Каркасный ИЖС не равен брусу, но в локальной базе ближайший объектный аналог сейчас
    # деревянный ИЖС. Это именно analog fallback, а не точный match шаблона.
    "каркас": {"дерев", "деревян", "брус", "бревен", "бревён"},
}

# Человекочитаемые подписи геометрических ASSUME-коэффициентов (для блока «Допущения»).
# Ключ нет в карте → показываем как есть (сырое имя из geometry шаблона).
_GEO_LABELS = {
    "H": "Высота этажа H, м",
    "roof_slope_k": "Коэф. скатной кровли (к площади застройки)",
    "found_section": "Сечение ленты фундамента, м²",
    "roof_flat_k": "Коэф. плоской кровли (к площади застройки)",
    "found_slab_t": "Толщина фундаментной плиты, м",
    "partition_k": "Коэф. перегородок (к площади этажа)",
}

# Этажность словом: одно/двух/трёх… → N.
_FLOORS_WORD = {
    "одноэтаж": 1, "однаэтаж": 1, "двухэтаж": 2, "двуэтаж": 2, "трёхэтаж": 3,
    "трехэтаж": 3, "четырёхэтаж": 4, "четырехэтаж": 4, "пятиэтаж": 5,
    "одноэтажн": 1, "двухэтажн": 2, "трёхэтажн": 3, "трехэтажн": 3,
    "один этаж": 1, "один этажа": 1, "в один этаж": 1,
    "два этажа": 2, "в два этажа": 2,
    "три этажа": 3, "в три этажа": 3,
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
    if not m:
        m = re.search(
            r"(?:м²|м2|м\s*кв|кв\.?\s*м|квадрат\w*|метр\w*)\D{0,8}(\d+(?:[.,]\d+)?)",
            ql,
        )
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


def merge_parsed_requests(texts: list[str], *, use_llm: bool = False) -> dict[str, Any]:
    """Несколько реплик диалога → одно состояние объектной сметы.

    Правило простое и воспроизводимое: каждое новое распознанное поле заменяет старое.
    Так уточнение «а давай два этажа» не конфликтует с прежним «один этаж».
    """
    merged: dict[str, Any] = {
        "object": None,
        "material": None,
        "floors": None,
        "area": None,
        "raw": "",
        "source": "dialog_state",
        "turns": [],
    }
    raw_parts: list[str] = []
    for text in texts:
        q = " ".join(str(text or "").split())
        if not q:
            continue
        parsed = parse_request(q, use_llm=use_llm)
        raw_parts.append(q)
        changed: dict[str, Any] = {}
        for key in ("object", "material", "floors", "area"):
            value = parsed.get(key)
            if value not in (None, ""):
                merged[key] = value
                changed[key] = value
        if changed:
            merged["turns"].append({"raw": q, "changed": changed})
    merged["raw"] = " ".join(raw_parts)
    return merged


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


def select_analog_template(
    parsed: dict[str, Any],
    *,
    path: str | None = None,
) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """Ближайший локальный шаблон, если точного match нет.

    Это не расширяет `match`: результат помечается как аналог и обязан попасть в ответ/trace.
    Нужен для поведения «нет точного шаблона — найди похожее в нашей базе», без фантазии LLM.
    """
    obj = str(parsed.get("object") or "").casefold().replace("ё", "е")
    mat = str(parsed.get("material") or "").casefold().replace("ё", "е")
    raw = str(parsed.get("raw") or "").casefold().replace("ё", "е")
    best: tuple[float, Optional[dict[str, Any]], list[str]] = (0.0, None, [])
    for tpl in load_templates(path):
        match = tpl.get("match") or {}
        objects = [str(o).casefold().replace("ё", "е") for o in match.get("object") or []]
        materials = [str(m).casefold().replace("ё", "е") for m in match.get("material") or []]
        score = 0.0
        reasons: list[str] = []
        if obj and any(o == obj or o in raw for o in objects):
            score += 5.0
            reasons.append(f"объект `{obj}` есть в match.object")
        elif obj in _HOUSE_OBJECT_WORDS and any(o in _HOUSE_OBJECT_WORDS for o in objects):
            score += 3.0
            reasons.append(f"объект `{obj}` относится к ИЖС/дому")
        if mat and materials:
            if any(m in raw or m.startswith(mat) for m in materials):
                score += 4.0
                reasons.append(f"материал `{mat}` совпал с match.material")
            elif any(m in _MATERIAL_ANALOGS.get(mat, set()) for m in materials):
                score += 2.0
                reasons.append(f"материал `{mat}` близок к деревянному ИЖС, но не точный матч")
            else:
                score -= 4.0
                reasons.append(f"материал `{mat}` не совместим с материалами шаблона")
        if any(token in raw for token in ("ижс", "дач", "коттедж")) and any(o in _HOUSE_OBJECT_WORDS for o in objects):
            score += 1.0
            reasons.append("назначение похоже на малоэтажный жилой объект")
        if score > best[0]:
            best = (score, tpl, reasons)
    score, tpl, reasons = best
    if tpl is None or score < 4.0:
        return None, None
    return tpl, {
        "status": "template_analog",
        "score": round(score, 2),
        "template_id": tpl.get("id"),
        "template_name": tpl.get("name"),
        "requested_object": parsed.get("object"),
        "requested_material": parsed.get("material"),
        "reasons": reasons,
        "warning": (
            "Точного объектного шаблона нет; расчёт выполнен по ближайшему локальному аналогу "
            "из config/domain/object_templates.yaml."
        ),
    }


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


def _formula_values(formula: str, ns: dict[str, float]) -> dict[str, float]:
    """Фактические значения переменных, которыми подставлена формула объёма."""
    values: dict[str, float] = {}
    for token in _FORMULA_IDENT_RE.findall(str(formula or "")):
        if token in ns:
            values[token] = round(_f(ns[token]), 6)
    return values


def _physical_qty(qty: Any, unit: str) -> tuple[float, str]:
    """Нормативный объём → физический: 4 × «100 м3» = 400 м³."""
    u = str(unit or "").strip()
    factor, base_u = 1.0, u
    m = _UNIT_FACTOR_RE.match(u)
    if m:
        factor = _f(m.group(1)) or 1.0
        base_u = m.group(2)
    base_u = base_u.replace("м2", "м²").replace("м3", "м³")
    return round(_f(qty) * factor, 2), base_u


def build_vor(template: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Шаблон + параметры → ВОР: позиции с ВЫЧИСЛЕННЫМИ объёмами. 0 LLM, объёмы из формул."""
    ns = _geometry(_f(params.get("area")), int(params.get("floors") or 1), template)
    positions: list[dict[str, Any]] = []
    for p in template.get("positions", []):
        if not p.get("code") or not p.get("qty_formula"):  # TODO-позиции (нет нормы/формулы) — пропуск
            continue
        qty = _eval_formula(p["qty_formula"], ns)
        phys_qty, phys_unit = _physical_qty(qty, p.get("unit", ""))
        positions.append({
            "code": p["code"], "name": p.get("name", ""), "unit": p.get("unit", ""),
            "qty": qty, "work_kind": p.get("work_kind", ""), "formula": p["qty_formula"],
            "formula_values": _formula_values(p["qty_formula"], ns),
            "physical_qty": phys_qty, "physical_unit": phys_unit,
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
    parsed_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Фраза → прикидка: parse → шаблон → ВОР → lsr_assembly.assemble. Локально, без сети.

    Возвращает {ok, parsed, template, vor, estimate, assumptions, error?}. ok=False — нет
    шаблона/площади/этажности (просим уточнить), прикидка не собирается.
    """
    from proxy.services.gesn_service import get_norm
    from proxy.services.lsr_assembly_service import assemble
    from proxy.services.nr_sp_service import resolve as resolve_nr_sp

    parsed = dict(parsed_context) if parsed_context else parse_request(text, use_llm=use_llm)
    if not parsed.get("raw"):
        parsed["raw"] = " ".join(str(text or "").split())

    if not parsed.get("area"):
        return {"ok": False, "parsed": parsed,
                "error": "Не распознана площадь — укажи «… площадью N м²»."}
    if not parsed.get("floors"):
        parsed = {**parsed, "floors": 1}  # этажность по умолчанию — 1 (явно фиксируем)

    tpl = select_template(parsed, path=templates_path)
    analog: Optional[dict[str, Any]] = None
    if tpl is None:
        tpl, analog = select_analog_template(parsed, path=templates_path)
        if tpl is None:
            have = [t.get("name") or t.get("id") for t in load_templates(templates_path)]
            have_str = "; ".join(h for h in have if h) or "—"
            return {"ok": False, "parsed": parsed,
                    "error": f"Нет шаблона или близкого аналога под объект/материал (есть: {have_str})."}

    vor = build_vor(tpl, parsed)

    # ВОР → позиции движка: НР/СП по виду работ (из work_kind), пометка отсутствующих норм.
    positions: list[dict[str, Any]] = []
    assembled_vor_positions: list[dict[str, Any]] = []
    missing_codes: list[str] = []
    for v in vor["positions"]:
        norm = get_norm(v["code"])  # ЛОКАЛЬНО, без сети
        if norm is None:
            missing_codes.append(v["code"])  # честно: нормы нет → в смету не идёт
            continue
        rs = resolve_nr_sp(v.get("work_kind") or norm.get("name", ""))
        assembled_vor_positions.append(v)
        positions.append({
            "code": v["code"], "name": v["name"], "unit": v["unit"], "qty": v["qty"],
            "section": v.get("work_kind", "") or "Конструктив",
            "nr_pct": rs["nr_pct"], "sp_pct": rs["sp_pct"],
        })

    lsr = assemble(positions, condition=condition) if positions else {
        "positions": [], "summary": {"positions": 0, "total": 0.0, "base_total": 0.0,
                                     "flags": [], "needs_price": 0}}

    # Хвост прикидки:
    #   1) ГЭСН-конструктив (проверяемая нижняя база);
    #   2) ASSUME-разделы, если ТЗ мутное и нет ВОР/чертежей;
    #   3) price_level_k — грубый переход к текущему уровню бюджета;
    #   4) непредвиденные + НДС.
    gesn_smr = round(_f(lsr.get("summary", {}).get("total")), 2)
    allowances = _estimate_allowances(tpl, parsed.get("raw", ""), gesn_smr)
    allowance_total = round(sum(_f(a.get("amount")) for a in allowances), 2)
    subtotal_base = round(gesn_smr + allowance_total, 2)
    price_level_k = _f(tpl.get("price_level_k") or 1.0) or 1.0
    smr = round(subtotal_base * price_level_k, 2)
    cont_pct, vat_pct = 2.0, 20.0
    contingency = round(smr * cont_pct / 100, 2)
    before_vat = round(smr + contingency, 2)
    vat = round(before_vat * vat_pct / 100, 2)
    grand_total = round(before_vat + vat, 2)
    totals = {
        "gesn_smr": gesn_smr, "allowance_total": allowance_total,
        "subtotal_base": subtotal_base, "price_level_k": price_level_k,
        "smr": smr, "contingency_pct": cont_pct, "contingency": contingency,
        "before_vat": before_vat, "vat_pct": vat_pct, "vat": vat, "grand_total": grand_total,
        "positions": len(positions), "allowance_positions": len(allowances),
    }

    scope_warnings = _scope_warnings(parsed.get("raw", ""), tpl)
    assumptions = _collect_assumptions(
        tpl, vor["params"], missing_codes, scope_warnings,
        allowances=allowances, price_level_k=price_level_k,
    )
    if analog:
        assumptions.insert(0, str(analog.get("warning") or "Расчёт выполнен по локальному аналогу."))
    defense = _build_defense(
        tpl=tpl,
        vor_positions=assembled_vor_positions,
        lsr_positions=lsr.get("positions") or [],
        allowances=allowances,
        totals=totals,
    )
    return {
        "ok": True,
        "parsed": parsed,
        "template": {"id": tpl.get("id"), "name": tpl.get("name")},
        "analog": analog,
        "vor": vor,
        "estimate": lsr,
        "allowances": allowances,
        "totals": totals,
        "missing_codes": missing_codes,
        "scope_warnings": scope_warnings,
        "quality": {
            "status": "rough_analog_object_assumed" if analog else "rough_full_object_assumed",
            "final_total_allowed": False,
            "reason": (
                "Точный шаблон отсутствует; использован ближайший локальный аналог. "
                if analog else ""
            ) + (
                "Мутное ТЗ: недостающие разделы и текущий уровень цен приняты допущениями; "
                "позиции с ресурсами без цены являются неполным ценовым покрытием."
            ),
        },
        "defense": defense,
        "assumptions": assumptions,
    }


def _build_defense(
    *,
    tpl: dict[str, Any],
    vor_positions: list[dict[str, Any]],
    lsr_positions: list[dict[str, Any]],
    allowances: list[dict[str, Any]],
    totals: dict[str, Any],
) -> dict[str, Any]:
    """Защитный слой расчёта: объём, цена, ценовое покрытие и границы доказательности."""
    from proxy.services.evidence_contract import DefenseClaim, DefensePack, DefenseStatus

    gesn_items: list[dict[str, Any]] = []
    claims: list[DefenseClaim] = []
    coverage_total = {"resources": 0, "priced": 0, "missing": 0, "by_source": {}}
    for v, ap in zip(vor_positions, lsr_positions):
        coverage = _resource_price_coverage(ap.get("resources") or [])
        coverage_total["resources"] += int(coverage["resources"])
        coverage_total["priced"] += int(coverage["priced"])
        coverage_total["missing"] += int(coverage["missing"])
        by_source = coverage_total["by_source"]
        for source, count in coverage["by_source"].items():
            by_source[source] = by_source.get(source, 0) + count
        base = ap.get("base") or {}
        gesn_items.append({
            "code": v.get("code"),
            "name": v.get("name") or ap.get("name"),
            "norm_unit": v.get("unit"),
            "norm_qty": v.get("qty"),
            "physical_qty": v.get("physical_qty"),
            "physical_unit": v.get("physical_unit"),
            "formula": v.get("formula"),
            "formula_values": v.get("formula_values") or {},
            "cost_build_up": {
                "ozp": round(_f(base.get("ozp")), 2),
                "em": round(_f(base.get("em")), 2),
                "mat": round(_f(base.get("mat")), 2),
                "direct": round(_f(base.get("direct")), 2),
                "fot": round(_f(base.get("fot")), 2),
                "nr": round(_f(base.get("nr")), 2),
                "sp": round(_f(base.get("sp")), 2),
                "total": round(_f(base.get("total")), 2),
            },
            "resource_price_coverage": coverage,
            "status": "PARTIAL_PRICE" if coverage["missing"] else "PRICED",
        })
        claim_status = DefenseStatus.PARTIAL if coverage["missing"] else DefenseStatus.COMPUTED
        gaps = []
        actions = []
        if coverage["missing"]:
            gaps.append(f"Нет цены у {coverage['missing']} ресурс(ов) позиции.")
            actions.append("Закрыть цены через ФГИС ЦС/КАЦ/КП или импорт ценовой книги.")
        claims.append(DefenseClaim(
            id=f"gesn:{v.get('code')}",
            domain="smeta.object_estimate.gesn_position",
            title=str(v.get("name") or v.get("code") or "ГЭСН-позиция"),
            statement=(
                f"{v.get('code')}: объём {v.get('physical_qty')} {v.get('physical_unit')} "
                f"и стоимость {round(_f(base.get('total')), 2)} ₽ рассчитаны кодом."
            ),
            status=claim_status,
            value=round(_f(base.get("total")), 2),
            unit="₽",
            source_refs=[f"ГЭСН-2022#{v.get('code')}"],
            formulas=[{
                "name": "qty_formula",
                "expr": v.get("formula"),
                "inputs": v.get("formula_values") or {},
                "norm_qty": v.get("qty"),
                "norm_unit": v.get("unit"),
                "physical_qty": v.get("physical_qty"),
                "physical_unit": v.get("physical_unit"),
            }],
            inputs=[{"name": "cost_build_up", "value": gesn_items[-1]["cost_build_up"]}],
            gaps=gaps,
            actions=actions,
            confidence=0.65 if coverage["missing"] else 0.9,
        ))
    allowance_payload = [
        {
            "id": a.get("id") or "",
            "label": a.get("label") or a.get("id") or "ASSUME-раздел",
            "pct_of_smr": _f(a.get("pct_of_smr")),
            "base": _f(totals.get("gesn_smr")),
            "amount": _f(a.get("amount")),
            "basis": "operator_template_assumption",
            "status": "ASSUMED_NOT_NORMATIVE",
        }
        for a in allowances
    ]
    for a in allowance_payload:
        claims.append(DefenseClaim(
            id=f"assume:{a['id']}",
            domain="smeta.object_estimate.allowance",
            title=str(a["label"]),
            statement=(
                f"{a['label']}: {round(_f(a['pct_of_smr']) * 100, 1)}% от ГЭСН-конструктива "
                f"= {round(_f(a['amount']), 2)} ₽."
            ),
            status=DefenseStatus.ASSUMED,
            value=round(_f(a["amount"]), 2),
            unit="₽",
            assumptions=["Укрупнённый процент шаблона, не нормативная позиция и не КП."],
            formulas=[{
                "name": "allowance_pct_of_gesn_smr",
                "expr": "gesn_smr * pct_of_smr",
                "inputs": {"gesn_smr": _f(totals.get("gesn_smr")), "pct_of_smr": a["pct_of_smr"]},
            }],
            actions=["Заменить ASSUME-раздел детальной ВОР/ЛСР/КП при наличии проектных данных."],
            confidence=0.35,
        ))
    claims.append(DefenseClaim(
        id="object_estimate:final_total",
        domain="smeta.object_estimate.total",
        title="Ориентир стоимости объекта с НДС",
        statement="Итог является бюджетным ориентиром по мутному ТЗ, а не защищаемой ЛСР.",
        status=DefenseStatus.NOT_DEFENSIBLE,
        value=round(_f(totals.get("grand_total")), 2),
        unit="₽",
        assumptions=[
            "Есть ASSUME-разделы.",
            "Коэффициент текущего уровня цен принят из шаблона.",
            "Есть незакрытые цены ресурсов." if coverage_total["missing"] else "Цены ресурсов закрыты.",
        ],
        formulas=[{
            "name": "object_grand_total",
            "expr": "(gesn_smr + allowance_total) * price_level_k * (1 + contingency_pct) * (1 + vat_pct)",
            "inputs": {
                "gesn_smr": totals.get("gesn_smr"),
                "allowance_total": totals.get("allowance_total"),
                "price_level_k": totals.get("price_level_k"),
                "contingency_pct": _f(totals.get("contingency_pct")) / 100.0,
                "vat_pct": _f(totals.get("vat_pct")) / 100.0,
            },
        }],
        gaps=[
            "Нет проектной ВОР/Ф9/КС-2 по всем разделам.",
            "Нет подтверждённого региона/квартала/индекса текущего уровня цен.",
            f"Нет цены у {coverage_total['missing']} ресурс(ов)." if coverage_total["missing"] else "",
        ],
        actions=[
            "Прикрепить проектные объёмы/смету/КС-2/папку проекта.",
            "Выбрать регион и квартал индексов.",
            "Закрыть недостающие цены ФГИС/КАЦ/КП.",
        ],
        confidence=0.25,
    ))
    pack = DefensePack(
        domain="smeta.object_estimate",
        title="Защита объектной прикидки",
        status=DefenseStatus.NOT_DEFENSIBLE,
        claims=claims,
        summary={
            "gesn_positions": len(gesn_items),
            "allowance_positions": len(allowance_payload),
            "grand_total": totals.get("grand_total"),
        },
        coverage=coverage_total,
        required_actions=[
            "Для защищаемой сметы приложить ВОР/Ф9/КС-2 или проектную папку.",
            "Закрыть цены ресурсов через ФГИС/КАЦ/КП.",
            "Заменить ASSUME-разделы детальными позициями.",
        ],
    )
    return {
        "template_id": tpl.get("id"),
        "gesn_positions": gesn_items,
        "allowance_positions": allowance_payload,
        "price_coverage": coverage_total,
        "price_level": {
            "k": _f(totals.get("price_level_k")) or 1.0,
            "basis": "ASSUME, не подтверждено индексом/регионом/кварталом",
        },
        "defensibility": {
            "status": "ORIENTIR_NOT_DEFENSIBLE_LSR",
            "reason": (
                "Можно защищать ход расчёта и нижнюю ГЭСН-базу, но нельзя защищать итог как "
                "детальную ЛСР без проектной ВОР, индексов/региона/квартала и закрытых цен ресурсов."
            ),
        },
        "contract": pack.payload(),
    }


def _resource_price_coverage(resources: list[dict[str, Any]]) -> dict[str, Any]:
    by_source: dict[str, int] = {}
    missing_examples: list[str] = []
    for r in resources:
        source = str(r.get("price_source") or "missing").strip() or "missing"
        by_source[source] = by_source.get(source, 0) + 1
        if source == "missing" and len(missing_examples) < 5:
            code = str(r.get("code") or "").strip()
            name = str(r.get("name") or "").strip()
            missing_examples.append(f"{code} {name}".strip())
    total = len(resources)
    missing = by_source.get("missing", 0)
    return {
        "resources": total,
        "priced": max(total - missing, 0),
        "missing": missing,
        "by_source": by_source,
        "missing_examples": missing_examples,
    }


def _collect_assumptions(
    tpl: dict[str, Any],
    params: dict[str, Any],
    missing: list[str],
    scope_warnings: list[str] | None = None,
    *,
    allowances: list[dict[str, Any]] | None = None,
    price_level_k: float = 1.0,
) -> list[str]:
    """Человекочитаемые допущения (геометрия/коэффициенты/пропуски) для прозрачности сметы.
    Коэффициенты берутся ДИНАМИЧЕСКИ из geometry шаблона — каждый тип объекта (дерево/
    монолит) несёт свои (скат vs плоская кровля, лента vs плита) и показывает только их."""
    geo = tpl.get("geometry") or {}
    out = [
        f"Пятно квадратное: периметр P = 4·√(S/N) = {params.get('P')} м "
        f"(S={params.get('S')} м², N={params.get('N')}, S₁={params.get('S1')} м²).",
    ]
    for k, v in geo.items():
        out.append(f"{_GEO_LABELS.get(k, k)} = {v} (ASSUME).")
    out.append("Объёмы — из формул шаблона над {S,N,P,H,S₁}; числа из норм ГЭСН (ADR-11, 0 LLM в расчёте).")
    if allowances:
        for item in allowances:
            out.append(
                f"{item.get('label')}: {round(_f(item.get('pct_of_smr')) * 100, 1)}% "
                "от ГЭСН-конструктива (ASSUME)."
            )
    if price_level_k != 1.0:
        out.append(f"Коэффициент текущего уровня цен k = {price_level_k} (ASSUME).")
    for warning in scope_warnings or []:
        out.append(warning)
    if missing:
        out.append(f"Нет нормы в локальной базе (пропущены): {', '.join(missing)}.")
    return out


def _estimate_allowances(tpl: dict[str, Any], raw: str, base_smr: float) -> list[dict[str, Any]]:
    """ASSUME-разделы для режима «мутное ТЗ → прикидка объекта целиком».

    `pct_of_smr=0.35` значит 35% от проверяемого ГЭСН-конструктива. Условные разделы
    включаются только по сигналам из запроса, если задан `applies_when_any`.
    """
    q = (raw or "").casefold().replace("ё", "е")
    out: list[dict[str, Any]] = []
    for item in tpl.get("allowances") or []:
        tokens = [str(t).casefold().replace("ё", "е") for t in item.get("applies_when_any") or []]
        if tokens and not any(t in q for t in tokens):
            continue
        pct = _f(item.get("pct_of_smr"))
        amount = round(base_smr * pct, 2)
        out.append({
            "id": item.get("id") or "",
            "label": item.get("label") or item.get("id") or "ASSUME-раздел",
            "pct_of_smr": pct,
            "amount": amount,
            "kind": "ASSUMED",
        })
    return out


def _scope_warnings(raw: str, tpl: dict[str, Any]) -> list[str]:
    """Явные части пользовательского задания, которые считаются только укрупнённо.

    Это не валидатор сметы, а защита от самой опасной ошибки UI: запрос содержит значимый
    объём работ, а параметрический шаблон молча прячет его внутри итога.
    """
    q = (raw or "").casefold().replace("ё", "е")
    tpl_id = str(tpl.get("id") or "")
    warnings: list[str] = []
    if tpl_id == "monolith_office" and any(token in q for token in ("подвал", "цоколь", "подзем")):
        warnings.append(
            "Подвал/подземная часть учтены укрупнённой ASSUME-добавкой; "
            "детальных земляных/гидроизоляционных позиций нет."
        )
    if re.search(r"\bсва(я|и|й|е|ю|ях|ям|ями|ев|ями)\b", q) or "винтов" in q:
        has_pile_position = any(
            "сва" in str(p.get("name") or "").casefold().replace("ё", "е")
            or "сва" in str(p.get("work_kind") or "").casefold().replace("ё", "е")
            for p in tpl.get("positions") or []
        )
        if not has_pile_position:
            warnings.append(
                "Свайный фундамент запрошен явно, но в выбранном шаблоне нет отдельных свайных "
                "позиций; нужна схема свай/ростверка или отдельный вариант шаблона."
            )
    if tpl_id == "wooden_house" and any(token in q for token in ("плоск", "мембран")):
        warnings.append(
            "Плоская кровля запрошена явно, но шаблон деревянного дома сейчас содержит скатную "
            "кровлю; нужен вариант кровельного пирога/узлов."
        )
    if any(token in q for token in ("крыльц", "террас", "веранд")):
        warnings.append(
            "Крыльцо/терраса не разложены отдельными ГЭСН-позициями; нужны размеры и конструкция."
        )
    if any(token in q for token in ("инженерк", "овик", "вк", "электр", "слаботоч", "отделк", "окн", "двер")):
        warnings.append("Инженерные сети/отделка/проёмы считаются только укрупнёнными ASSUME-разделами.")
    return warnings
