"""Сметный ХАРНЕСС (экспериментальный профиль smeta_harness) — петля инструментов + Quality Gate 1.

СТАТУС (фиксируем строго, чтобы через неделю никто не принял 6.9 млрд за «почти смету»):
  ✅ ORCHESTRATION ДОКАЗАН: модель раскладывает объект, дёргает типизированные инструменты,
     получает структурные результаты, собирает предварительный ответ. Числа — из инструментов.
  ⚠️ ESTIMATE QUALITY НЕ ДОКАЗАН: нормы/объёмы/итог НЕ валидны как смета. Это инженерный
     прототип петли, НЕ сметный продукт.

Quality Gate 1 (этот файл) — НЕ «красота», а предохранители, чтобы ошибочная позиция НЕ
доходила до итоговой суммы (главный дефект). Порядок (по ТЗ):
  1. UNIT CONTRACT — модель даёт ФИЗИЧЕСКИЙ объём; КОД переводит в измеритель нормы
     (14400 м³ при норме «100 м3» → 144 нормо-ед, не 14400). Несовместимая единица → needs_input.
  2. WORK_FAMILY → ALLOWED_COLLECTIONS — норма из запрещённого сборника (29-02 для земли) не
     попадает в позицию (детерминированный whitelist по сборникам).
  3. MAGNITUDE GUARD — грубые sanity-границы (объём котлована ≤ пятно×глубина×запас). Превышение
     на порядок → позиция rejected, в итог НЕ идёт.
  4. Итог НЕ формируется как сумма, если есть critical-rejected позиции.

Число НИКОГДА не из текста модели — только из формул/get_norm, после Gate. complete(messages)->str
инъектируется (тест — скрипт; прод — облако/MLX).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, Callable

from proxy.services.object_estimate_service import _eval_formula, _f, _geometry

# ── единицы измерения (UNIT CONTRACT) ────────────────────────────────────────────────────

def _canon_unit(u: str) -> str:
    """Канонизировать единицу: м³/м²/куб.м → м3/м2; нижний регистр; без пробелов."""
    s = (u or "").strip().lower().replace("³", "3").replace("²", "2")
    s = s.replace("куб.м", "м3").replace("кв.м", "м2").replace("куб м", "м3").replace("кв м", "м2")
    return re.sub(r"\s+", "", s)


def _norm_unit_factor(unit: str) -> tuple[float, str]:
    """Измеритель нормы → (множитель, базовая единица). «100 м3»→(100,«м3»); «10 м2»→(10,«м2»);
    «м3»→(1,«м3»); «т»→(1,«т»)."""
    m = re.match(r"\s*(\d+)?\s*(.+)", str(unit or "").strip())
    if not m:
        return 1.0, _canon_unit(unit)
    factor = float(m.group(1)) if m.group(1) else 1.0
    return factor, _canon_unit(m.group(2))


def _units_compatible(physical_unit: str, norm_base_unit: str) -> bool:
    return _canon_unit(physical_unit) == _canon_unit(norm_base_unit)


# ── применимость: семейство работ → разрешённые сборники ГЭСН ────────────────────────────

WORK_FAMILY_COLLECTIONS: dict[str, set[str]] = {
    "earthworks": {"01"},                       # земляные
    "foundation": {"05", "06"},                 # фундаменты/основания
    "concrete_monolithic": {"06"},              # монолит ж/б
    "concrete_precast": {"07"},                 # сборный ж/б
    "masonry": {"08"},                          # каменные
    "metal": {"09"},                            # металлоконструкции
    "floors": {"11"},                           # полы
    "roofing": {"12"},                          # кровли
    "waterproofing": {"08", "12"},              # гидро/тепло-изоляция
    "finishes": {"15"},                         # отделка
}


def _collection_of(code: str) -> str:
    m = re.match(r"\s*(\d{2})", str(code or ""))
    return m.group(1) if m else ""


# ── Quality Gate 2: ПРИМЕНИМОСТЬ НОРМЫ (барьер между кандидатом и числом) ─────────────────
# Фильтр по сборнику — крупное сито (06-22 «защитная оболочка реактора» проходит как сб.06).
# Поэтому ещё: запретные признаки в названии + обязательные признаки семейства + чёрный список
# подразделов. Это предохранитель, НЕ онтология — заводится руками под реальные провалы.

# Признаки «не та норма» в названии (спец/нерелевантные сооружения).
_FORBIDDEN_TITLE_ANCHORS = (
    "реактор", "оболочк", "защитн", "шахт", "тоннел", "метрополит", "спецсооруж", "башенн",
    "копр", "резервуар", "силос", "градирн", "доменн", "плотин", "судов", "вагон", "мост",
)
# Обязательные признаки семейства — иначе ambiguous (название не похоже на работу).
_FAMILY_POSITIVE_ANCHORS: dict[str, tuple[str, ...]] = {
    "earthworks": ("грунт", "котлован", "траншея", "разработ", "выемк", "насып", "землян", "разраб"),
    "foundation": ("фундамент", "основани", "плит", "бетон"),
    "concrete_monolithic": ("бетон", "монолит", "железобетон", "плит", "стен", "перекрыт", "колонн", "фундамент"),
    "concrete_precast": ("сборн", "панел", "плит", "блок"),
    "masonry": ("кладк", "стен", "перегородк", "кирпич", "блок"),
    "metal": ("металл", "сталь", "конструкц", "балк", "ферм"),
    "floors": ("пол", "стяжк", "покрыт"),
    "roofing": ("кровл", "покрыт", "рулон", "мембран"),
    "waterproofing": ("гидроизол", "изоляц", "оклеечн", "обмазочн", "мастичн"),
    "finishes": ("отделк", "штукатур", "окрас", "облицов"),
}
# Чёрный список подразделов под семейство (реальные провалы паркинга).
_FAMILY_DENIED_PREFIXES: dict[str, tuple[str, ...]] = {
    "concrete_monolithic": ("06-22", "06-13", "06-14"),   # реактор/ёмкостные/спец
    "foundation": ("06-22",),
}


def check_applicability(code: str, norm_name: str, work_family: str) -> tuple[str, list[str]]:
    """Кандидат → accepted | ambiguous | rejected (+ причины). Барьер перед привязкой нормы."""
    name = (norm_name or "").lower()
    for a in _FORBIDDEN_TITLE_ANCHORS:
        if a in name:
            return "rejected", [f"запретный признак в названии: «{a}»"]
    for pref in _FAMILY_DENIED_PREFIXES.get(work_family, ()):
        if str(code).startswith(pref):
            return "rejected", [f"подраздел {pref} не для {work_family}"]
    pos = _FAMILY_POSITIVE_ANCHORS.get(work_family, ())
    if pos and not any(a in name for a in pos):
        return "ambiguous", [f"в названии нет признаков семейства {work_family}"]
    return "accepted", []


# ── search_norm: тонкий кандидатор + фильтр применимости ─────────────────────────────────

@lru_cache(maxsize=1)
def _norm_index() -> list[tuple[str, str, str]]:
    from proxy.services.gesn_service import load_base_norms
    return [(code, str(n.get("name", "")).lower(), str(n.get("unit", "")))
            for code, n in (load_base_norms() or {}).items()]


# Gate 3: позитивные/негативные признаки названия по ТИПУ ЭЛЕМЕНТА (точнее семьи).
_ELEMENT_ANCHORS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "excavation":          (("разработ", "грунт", "котлован", "выемк", "землян"), ("тоннел", "шахт", "скальн", "подводн")),
    "concrete_preparation": (("подготовк", "бетонн", "щебен", "основани"), ()),
    "foundation_slab":     (("плит", "фундамент", "бетон", "железобетон", "монолит"), ()),
    "foundation":          (("фундамент", "основани", "бетон"), ()),
    "monolithic_wall":     (("стен", "бетонирован", "бетон", "монолит", "железобетон"), ()),
    "monolithic_slab":     (("перекрыт", "плит", "бетонирован", "бетон", "монолит"), ()),
    "column":              (("колонн", "бетон", "монолит"), ()),
    "waterproofing":       (("гидроизол", "изоляц", "оклеечн", "обмазочн", "мастичн"), ()),
    "roofing":             (("кровл", "покрыт", "рулон", "мембран"), ()),
}


def _score_candidate(words: list[str], code: str, name: str, unit: str, *, work_family: str,
                     element_type: str, action: str, phys_unit: str) -> tuple[float, dict[str, float]] | None:
    """Структурный скоринг кандидата (прозрачный score_parts). Нет лексич. совпадения → None."""
    fts = sum(1 for w in words if w in name)
    if not fts:
        return None
    parts: dict[str, float] = {"fts": float(fts)}
    pos, neg = _ELEMENT_ANCHORS.get(element_type, ((), ()))
    parts["element"] = 1.5 * sum(1 for a in pos if a in name)
    parts["element_neg"] = -2.0 * sum(1 for a in neg if a in name)
    parts["family"] = 1.0 if any(a in name for a in _FAMILY_POSITIVE_ANCHORS.get(work_family, ())) else 0.0
    parts["action"] = 0.8 if (action and action.lower()[:5] and action.lower()[:5] in name) else 0.0
    _, base = _norm_unit_factor(unit)
    parts["unit"] = 1.0 if (phys_unit and _units_compatible(phys_unit, base)) else 0.0
    # тяжёлые штрафы: спец/нерелевантные сооружения и запрещённые подразделы тонут (но в выдаче видны)
    parts["forbidden"] = -5.0 * sum(1 for a in _FORBIDDEN_TITLE_ANCHORS if a in name)
    parts["denied_subsection"] = -5.0 if any(code.startswith(p) for p in _FAMILY_DENIED_PREFIXES.get(work_family, ())) else 0.0
    parts["collection"] = 1.0 if _collection_of(code) in WORK_FAMILY_COLLECTIONS.get(work_family, set()) else -3.0
    return round(sum(parts.values()), 2), {k: round(v, 2) for k, v in parts.items() if v}


def search_norm(work_description: str, *, work_family: str = "", element_type: str = "",
                action: str = "", unit_hint: str = "", top_k: int = 6) -> dict[str, Any]:
    """Gate 3: КАНДИДАТОР (не выбирает норму). Структурный ranking по work_family/element_type/
    action/unit/anchors — хорошие general всплывают, спец-коды штрафуются и тонут (но видны в trace).
    applicability_status метит каждого; bind (add_position) остаётся финальным барьером."""
    words = [w for w in re.findall(r"[а-яёa-z0-9]{3,}", (work_description or "").lower())]
    if not words:
        return {"status": "not_found", "candidates": [], "missing_inputs": ["work_description"]}
    uh = _canon_unit(unit_hint)
    scored: list[tuple[float, dict, str, str, str]] = []
    for code, name, unit in _norm_index():
        sc = _score_candidate(words, code, name, unit, work_family=work_family,
                              element_type=element_type, action=action, phys_unit=uh)
        if sc is None:
            continue
        scored.append((sc[0], sc[1], code, name, unit))
    if not scored:
        return {"status": "not_found", "candidates": [], "hint": "переформулируй work_description"}
    scored.sort(key=lambda t: (-t[0], t[2]))

    candidates = []
    for total, parts, c, nm, u in scored[:top_k]:
        factor, base = _norm_unit_factor(u)
        appl, reasons = check_applicability(c, nm, work_family)
        candidates.append({"norm_code": c, "title": nm, "collection": _collection_of(c),
                           "measure_unit": u, "base_unit": base,
                           "unit_compatible": (not uh) or _units_compatible(uh, base),
                           "applicability_status": appl, "rejection_reasons": reasons,
                           "score_total": total, "score_parts": parts})
    # found, если лидер ПРИМЕНИМ и заметно сильнее второго; иначе ambiguous
    top = candidates[0]
    clear_lead = len(candidates) == 1 or top["score_total"] >= candidates[1]["score_total"] + 2.0
    status = "found" if (top["applicability_status"] == "accepted" and clear_lead) else "ambiguous"
    return {"status": status, "work_family": work_family, "element_type": element_type,
            "candidates": candidates}


# ── magnitude guard: грубые порядковые границы ───────────────────────────────────────────

def _magnitude_check(physical_unit: str, qty: float, geom: dict[str, Any]) -> tuple[bool, float | None, str]:
    """Физический объём против грубой верхней границы из геометрии. Ловит порядковый бред
    (1.44 млн м³ на 4800 м²), НЕ придирается к 2×. ok, bound, reason."""
    base = _canon_unit(physical_unit)
    S = _f(geom.get("S")); S1 = _f(geom.get("S1")); N = _f(geom.get("N")) or 1
    if base == "м3":
        bound = max(S1 * (N * 4.0 + 15.0) * 2.0, 1.0)   # пятно × (высота+глубина) × запас 2
        return qty <= bound, round(bound, 1), "объём > пятно×высота×запас (вероятно ×100 от единицы)"
    if base == "м2":
        bound = max(S * 6.0, 1.0)                        # площади работ ≤ 6× общей площади
        return qty <= bound, round(bound, 1), "площадь работ > 6× площади объекта"
    return True, None, ""


# ── петля ────────────────────────────────────────────────────────────────────────────────

_REQUIRED_SCHEMA = ("object_type", "area_total_m2")

SYSTEM_PROMPT = (
    "Ты — инженер-сметчик. Разложи строительный ОБЪЕКТ в смету через ИНСТРУМЕНТЫ. Числа сам НЕ "
    "пиши и единицы НЕ пересчитывай — это делает код. Отвечай РОВНО одним JSON.\n\n"
    "Шаги:\n"
    "1) {\"tool\":\"propose_schema\",\"args\":{\"object_type\":..,\"area_total_m2\":..,"
    "\"levels_below_ground\":..,\"structural_system\":..,\"missing_inputs\":[..]}} — ПЕРВЫМ. "
    "Код вернёт геометрию {S,N,S1,P,H}.\n"
    "2) {\"tool\":\"search_norm\",\"args\":{\"work_description\":\"..\",\"work_family\":"
    "\"earthworks|foundation|concrete_monolithic|masonry|roofing|waterproofing|floors\","
    "\"element_type\":\"excavation|concrete_preparation|foundation_slab|monolithic_wall|"
    "monolithic_slab|column|waterproofing\",\"action\":\"бетонирование|разработка|..\","
    "\"unit_hint\":\"м3|м2\"}} — кандидаты ГЭСН (ранжируются; спец-коды тонут). Бери из них "
    "тот, у кого applicability_status=accepted.\n"
    "3) {\"tool\":\"add_position\",\"args\":{\"work\":\"..\",\"code\":\"NN-NN-NNN-NN\","
    "\"work_family\":\"..\",\"physical_unit\":\"м3|м2\",\"qty_formula\":\"<ФИЗИЧЕСКИЙ объём над "
    "S,N,S1,P,H, БЕЗ деления на измеритель>\",\"assumptions\":[..]}} — код сам переведёт в "
    "измеритель нормы и проверит единицы/применимость/магнитуду. Нет параметра в формуле → "
    "позиция станет needs_input (это НОРМАЛЬНО).\n"
    "4) {\"final\":true} — собрать (ПРЕДВАРИТЕЛЬНО).\n\n"
    "Подземный паркинг: котлован(earthworks), гидроизоляция(waterproofing), фунд.плита+стены+"
    "перекрытия(concrete_monolithic). Один JSON за ход; коды — только из search_norm."
)


def _add_position(args: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Quality Gate 1: формула→физ.объём → проверки (применимость/единицы/магнитуда) → перевод
    в измеритель нормы. Любой провал → позиция помечается, в итог критичное НЕ идёт."""
    from proxy.services.gesn_service import get_norm

    if not state.get("geom"):
        return {"ok": False, "error": "сначала propose_schema с площадью"}
    code = str(args.get("code", "")).strip()
    norm = get_norm(code)
    family = str(args.get("work_family", ""))
    base_pos = {"work": args.get("work", ""), "code": code, "work_family": family,
                "physical_unit": _canon_unit(args.get("physical_unit", "")),
                "assumptions": list(args.get("assumptions", []) or [])}

    if norm is None:
        state["positions"].append({**base_pos, "status": "rejected_norm", "reason": "кода нет в базе ГЭСН"})
        return {"ok": False, "status": "rejected_norm", "error": f"код {code} не в базе"}
    # применимость сборника
    allowed = WORK_FAMILY_COLLECTIONS.get(family, set())
    if allowed and _collection_of(code) not in allowed:
        state["positions"].append({**base_pos, "status": "rejected_collection",
                                   "reason": f"сборник {_collection_of(code)} не для {family}"})
        return {"ok": True, "status": "rejected_collection",
                "reason": f"сборник {_collection_of(code)} не разрешён для {family} — возьми из search_norm"}
    # Gate 2: ПРИМЕНИМОСТЬ нормы (bind-барьер) — кривой кандидат (реактор/спец/не та работа) НЕ
    # становится основанием числа. accepted → считаем; rejected/ambiguous → в итог не идёт.
    appl, appl_reasons = check_applicability(code, norm.get("name", ""), family)
    if appl != "accepted":
        st = "rejected_applicability" if appl == "rejected" else "ambiguous"
        state["positions"].append({**base_pos, "status": st, "reason": "; ".join(appl_reasons),
                                   "candidate": code})
        return {"ok": True, "status": st, "reason": "; ".join(appl_reasons),
                "note": "норма не подтверждена применимостью — возьми accepted из search_norm"}
    # физический объём из формулы
    try:
        phys = _eval_formula(str(args.get("qty_formula", "")), state["geom"])
    except Exception as e:  # нет переменной → needs_input, НЕ считаем молча
        state["positions"].append({**base_pos, "status": "needs_input", "reason": str(e)[:80]})
        return {"ok": True, "status": "needs_input", "reason": str(e)[:80]}
    # единицы: физическая ↔ базовая единица нормы
    factor, base_unit = _norm_unit_factor(norm.get("unit", ""))
    if not _units_compatible(base_pos["physical_unit"], base_unit):
        state["positions"].append({**base_pos, "status": "needs_input", "phys_qty": phys,
                                   "reason": f"единица {base_pos['physical_unit']} ≠ {base_unit} нормы"})
        return {"ok": True, "status": "needs_input",
                "reason": f"единица {base_pos['physical_unit']} несовместима с {base_unit} нормы"}
    # magnitude guard (на ФИЗИЧЕСКОМ объёме)
    mag_ok, bound, mag_reason = _magnitude_check(base_pos["physical_unit"], phys, state["geom"])
    if not mag_ok:
        state["positions"].append({**base_pos, "status": "rejected_magnitude", "phys_qty": phys,
                                   "bound": bound, "reason": mag_reason})
        return {"ok": True, "status": "rejected_magnitude", "phys_qty": phys, "upper_bound": bound,
                "reason": mag_reason + " — проверь формулу"}
    # перевод в измеритель нормы (КОД, не модель)
    qty_for_estimate = round(phys / factor, 6) if factor else phys
    state["positions"].append({**base_pos, "status": "computed", "phys_qty": phys,
                               "qty": qty_for_estimate, "norm_unit": norm.get("unit", ""),
                               "conversion": f"{phys} / {factor}"})
    return {"ok": True, "status": "computed", "phys_qty": phys, "norm_unit": norm.get("unit", ""),
            "quantity_for_estimate": qty_for_estimate, "positions_so_far": len(state["positions"])}


def _exec_tool(name: str, args: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "propose_schema":
            missing_required = [k for k in _REQUIRED_SCHEMA if not args.get(k)]
            area = _f(args.get("area_total_m2"))
            state["schema"] = args
            if not missing_required and area:
                levels = int(_f(args.get("levels_below_ground")) or _f(args.get("floors")) or 1) or 1
                state["geom"] = _geometry(area, levels, {"geometry": {"H": 3.0}})
                return {"ok": True, "geometry": {k: round(v, 3) for k, v in state["geom"].items()},
                        "missing_inputs": list(args.get("missing_inputs", []) or [])}
            return {"ok": False, "missing_required": missing_required}
        if name == "search_norm":
            return search_norm(str(args.get("work_description", "")),
                               work_family=str(args.get("work_family", "")),
                               element_type=str(args.get("element_type", "")),
                               action=str(args.get("action", "")),
                               unit_hint=str(args.get("unit_hint", "")))
        if name == "add_position":
            return _add_position(args, state)
        return {"ok": False, "error": f"неизвестный инструмент {name!r}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


_CRITICAL = {"rejected_magnitude", "rejected_collection", "rejected_norm",
             "rejected_applicability", "ambiguous"}


def _finalize(state: dict[str, Any], *, note: str = "") -> dict[str, Any]:
    """Сборка с Gate 1+2: считаем ТОЛЬКО computed (accepted-норма). Итог:
    complete (всё посчитано) | partial (есть computed + критичные/нет данных) | blocked (ничего).
    partial_total показываем как диагностику; final_total — только при complete (Codex Gate 2)."""
    from proxy.services.gesn_service import get_norm
    from proxy.services.lsr_assembly_service import assemble
    from proxy.services.nr_sp_service import resolve as resolve_nr_sp

    buckets: dict[str, list] = {"computed": [], "needs_input": [], "rejected": [], "by_assumption": []}
    asm = []
    for p in state.get("positions", []):
        st = p.get("status")
        if st in _CRITICAL:
            buckets["rejected"].append(p)
            continue
        if st == "needs_input":
            buckets["needs_input"].append(p)
            continue
        if st == "computed":
            buckets["computed"].append(p)
            if p.get("assumptions"):
                buckets["by_assumption"].append(p)
            norm = get_norm(p["code"])
            rs = resolve_nr_sp((norm or {}).get("name", ""))
            asm.append({"code": p["code"], "name": p.get("work") or (norm or {}).get("name", ""),
                        "unit": p.get("norm_unit", ""), "qty": p["qty"], "section": "Конструктив",
                        "nr_pct": rs["nr_pct"], "sp_pct": rs["sp_pct"]})

    lsr = assemble(asm) if asm else {"summary": {"total": 0.0}}
    smr = round(_f(lsr.get("summary", {}).get("total")), 2)
    cont = round(smr * 0.02, 2)
    vat = round((smr + cont) * 0.20, 2)
    partial = {"smr": smr, "contingency": cont, "vat": vat,
               "grand_total": round(smr + cont + vat, 2), "positions": len(buckets["computed"])}
    has_critical = bool(buckets["rejected"]) or bool(buckets["needs_input"])
    if not buckets["computed"]:
        total_status = "blocked"
    elif has_critical:
        total_status = "partial"
    else:
        total_status = "complete"
    blockers = [{"position": p.get("work", ""), "reason": p.get("status"),
                 "candidate": p.get("code"), "detail": p.get("reason", "")} for p in buckets["rejected"]]
    return {
        "ok": bool(buckets["computed"]),
        "preliminary": True,
        "total_status": total_status,            # blocked | partial | complete
        "partial_total": partial if buckets["computed"] else None,
        "final_total": partial if total_status == "complete" else None,
        "blockers": blockers,
        "schema": state.get("schema", {}),
        "computed": buckets["computed"],
        "needs_input": buckets["needs_input"],
        "rejected": buckets["rejected"],
        "by_assumption": buckets["by_assumption"],
        "estimate": lsr,
        "steps": state.get("steps", 0),
        "note": note,
        "source": "harness",
    }


def run_estimate_harness(question: str, complete: Callable[[list[dict[str, str]]], str],
                         *, max_steps: int = 16) -> dict[str, Any]:
    state: dict[str, Any] = {"schema": {}, "geom": {}, "positions": [], "steps": 0}
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Объект: {question}\nНачни с propose_schema."},
    ]
    trace: list[dict[str, Any]] = []
    for _ in range(max_steps):
        state["steps"] += 1
        raw = complete(messages) or ""
        call = _extract_json(raw)
        messages.append({"role": "assistant", "content": raw[:1500]})
        if call is None:
            obs: dict[str, Any] = {"ok": False, "error": "ответь РОВНО одним JSON {tool,args} или {final:true}"}
        elif call.get("final") or call.get("tool") == "finalize":
            res = _finalize(state)
            res["trace"] = trace
            return res
        else:
            tool = str(call.get("tool", ""))
            obs = _exec_tool(tool, call.get("args", {}) or {}, state)
            trace.append({"tool": tool, "status": obs.get("status") or ("ok" if obs.get("ok") else "err")})
        messages.append({"role": "user", "content": json.dumps(obs, ensure_ascii=False)})
    res = _finalize(state, note=f"достигнут лимит {max_steps} шагов")
    res["trace"] = trace
    return res


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None
