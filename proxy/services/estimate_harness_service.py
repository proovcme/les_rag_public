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

from proxy.services.estimate_math_service import _eval_formula, _f, _geometry

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
    "wood": {"10"},                             # деревянные конструкции
    "floors": {"11"},                           # полы
    "roofing": {"12"},                          # кровли
    "waterproofing": {"08", "12"},              # гидро/тепло-изоляция
    "finishes": {"15"},                         # отделка
}

_ELEMENT_DEFAULT_FAMILY: dict[str, str] = {
    "excavation": "earthworks",
    "concrete_preparation": "concrete_monolithic",
    "foundation_slab": "concrete_monolithic",
    "foundation": "foundation",
    "wood_wall": "wood",
    "metal_assembly": "metal",
    "pile": "foundation",
    "monolithic_wall": "concrete_monolithic",
    "monolithic_slab": "concrete_monolithic",
    "column": "concrete_monolithic",
    "waterproofing": "waterproofing",
    "roofing": "roofing",
}

_ACTION_ALIASES: dict[str, str] = {
    "assemble": "монтаж",
    "assembly": "монтаж",
    "cast": "бетонирование",
    "pour": "бетонирование",
    "excavate": "разработка",
    "remove": "разработка",
    "dig": "разработка",
    "install": "устройство",
    "prepare": "устройство",
}

_UNIT_ALIASES: dict[str, str] = {
    "m3": "м3",
    "m2": "м2",
    "t": "т",
    "ton": "т",
    "tons": "т",
    "tonne": "т",
    "tonnes": "т",
    "piece": "",
    "pcs": "",
    "шт": "",
}


def _collection_of(code: str) -> str:
    m = re.search(r"(?<!\d)(\d{2})-\d{2}-\d{3}-\d{2}", str(code or ""))
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
    "foundation": ("фундамент", "основани", "плит", "бетон", "сва", "ростверк"),
    "concrete_monolithic": ("бетон", "монолит", "железобетон", "плит", "стен", "перекрыт", "колонн", "фундамент"),
    "concrete_precast": ("сборн", "панел", "плит", "блок"),
    "masonry": ("кладк", "стен", "перегородк", "кирпич", "блок"),
    "metal": ("металл", "сталь", "конструкц", "балк", "ферм"),
    "wood": ("дерев", "брус", "бревн", "каркас", "стен", "перекрыт", "стропил"),
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
    allowed = WORK_FAMILY_COLLECTIONS.get(work_family)
    collection = _collection_of(code)
    if allowed and collection and collection not in allowed:
        return "rejected", [f"сборник {collection} не разрешён для {work_family}"]
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
    "wood_wall":           (("дерев", "брус", "бревн", "стен", "каркас"), ("линолеум", "грунтовк", "окрас")),
    "metal_assembly":      (("монтаж", "установ", "металл", "сталь", "конструкц", "каркас", "балк", "ферм"),
                             ("бак", "конвейер", "подстанц", "кабел", "автокоптил", "сцен")),
    "pile":                (("сва", "оголов", "ростверк"), ("насосн", "мелиоративн")),
    "monolithic_wall":     (("стен", "бетонирован", "бетон", "монолит", "железобетон"), ()),
    "monolithic_slab":     (("перекрыт", "плит", "бетонирован", "бетон", "монолит"), ()),
    "column":              (("колонн", "бетон", "монолит"), ()),
    "waterproofing":       (("гидроизол", "изоляц", "оклеечн", "обмазочн", "мастичн"), ()),
    "roofing":             (("кровл", "покрыт", "рулон", "мембран"), ()),
}

_ELEMENT_TEXT_SIGNALS: tuple[tuple[str, str, str], ...] = (
    ("wood_wall", "wood", r"\b(?:дерев|брус|бревн|каркасно[- ]?щит|каркасн\w*\s+стен|стен\w*\s+каркас)"),
    ("pile", "foundation", r"\b(?:сва|ростверк|свайн)"),
    ("roofing", "roofing", r"\b(?:кровл|стропил|двускат|плоск\w*\s+кров)"),
    ("excavation", "earthworks", r"\b(?:котлован|грунт|транше|выемк|землян|разработк)"),
    ("waterproofing", "waterproofing", r"\b(?:гидроизол|изоляц|обмазочн|оклеечн)"),
    ("foundation_slab", "concrete_monolithic", r"\b(?:фундаментн\w*\s+плит|плитн\w*\s+фундамент)"),
    ("monolithic_wall", "concrete_monolithic", r"\b(?:монолитн\w*\s+стен|бетонирован\w*\s+стен)"),
    ("floors", "floors", r"\b(?:пол|стяжк)"),
)


def _normalize_action(action: str) -> str:
    a = (action or "").strip().lower()
    return _ACTION_ALIASES.get(a, action)


def _normalize_unit_hint(unit: str) -> str:
    u = _canon_unit(unit)
    return _UNIT_ALIASES.get(u, u if u in {"м3", "м2", "т"} else "")


def _normalize_work_item(item: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Нормализовать tool-аргументы модели перед поиском ГЭСН.

    Это не состав работ и не выбор нормы: модель уже дала work item, а harness приводит
    family/element/action/unit к словарю инструмента, чтобы `search_norm` не уходил в очевидно
    чужой сборник из-за терминологического шума.
    """
    norm = dict(item)
    corrections: list[str] = []
    text = f"{norm.get('work', '')} {norm.get('work_description', '')}".lower()
    family = str(norm.get("work_family") or "")
    element = str(norm.get("element_type") or "")

    for inferred_element, inferred_family, pattern in _ELEMENT_TEXT_SIGNALS:
        if re.search(pattern, text):
            if element != inferred_element:
                corrections.append(f"element_type:{element or '—'}→{inferred_element}")
                norm["element_type"] = inferred_element
                element = inferred_element
            if family != inferred_family:
                corrections.append(f"work_family:{family or '—'}→{inferred_family}")
                norm["work_family"] = inferred_family
                family = inferred_family
            break

    default_family = _ELEMENT_DEFAULT_FAMILY.get(element)
    if default_family and family and family != default_family:
        corrections.append(f"work_family:{family}→{default_family}")
        norm["work_family"] = default_family
    elif default_family and not family:
        corrections.append(f"work_family:—→{default_family}")
        norm["work_family"] = default_family

    action = str(norm.get("action") or "")
    normalized_action = _normalize_action(action)
    if normalized_action != action:
        corrections.append(f"action:{action}→{normalized_action}")
        norm["action"] = normalized_action

    unit = str(norm.get("unit_hint") or "")
    normalized_unit = _normalize_unit_hint(unit)
    if normalized_unit != _canon_unit(unit):
        corrections.append(f"unit_hint:{unit or '—'}→{normalized_unit or '—'}")
        norm["unit_hint"] = normalized_unit
    else:
        norm["unit_hint"] = normalized_unit
    return norm, corrections


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
    selection = _candidate_selection(candidates)
    status = "found" if selection["action"] == "bind_top_candidate" else "ambiguous"
    return {"status": status, "work_family": work_family, "element_type": element_type,
            "candidates": candidates, "selection": selection}


def _candidate_reason_labels(candidate: dict[str, Any]) -> list[str]:
    """Human-readable explanation of why a candidate rose or sank in the shortlist."""
    parts = candidate.get("score_parts") if isinstance(candidate.get("score_parts"), dict) else {}
    labels: list[str] = []
    if candidate.get("applicability_status") == "accepted":
        labels.append("применимость по сборнику и названию подтверждена")
    elif candidate.get("applicability_status") == "ambiguous":
        labels.append("применимость требует выбора модели")
    elif candidate.get("applicability_status") == "rejected":
        labels.append("кандидат отклонён фильтром применимости")
    if parts.get("collection", 0) > 0:
        labels.append("сборник соответствует семейству работ")
    elif parts.get("collection", 0) < 0:
        labels.append("сборник не соответствует семейству работ")
    if parts.get("unit", 0) > 0:
        labels.append("единица измерения совпадает")
    if parts.get("element", 0) > 0:
        labels.append("есть признаки нужного элемента")
    if parts.get("family", 0) > 0:
        labels.append("есть признаки семейства работ")
    if parts.get("action", 0) > 0:
        labels.append("совпало действие работы")
    if parts.get("forbidden", 0) < 0 or parts.get("denied_subsection", 0) < 0:
        labels.append("есть признаки специальной/неподходящей нормы")
    return labels[:6]


def _candidate_shortlist(candidates: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    short: list[dict[str, Any]] = []
    for c in candidates[:limit]:
        short.append({
            "norm_code": c.get("norm_code", ""),
            "title": c.get("title", ""),
            "measure_unit": c.get("measure_unit", ""),
            "score_total": c.get("score_total", 0),
            "score_parts": c.get("score_parts", {}),
            "applicability_status": c.get("applicability_status", ""),
            "unit_compatible": c.get("unit_compatible", True),
            "reasons": _candidate_reason_labels(c),
        })
    return short


def _candidate_selection(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Explain whether the shortlist is clear enough to bind, or should go back to the model.

    The harness ranks and gates; it does not invent a work item. A top candidate is bindable only
    when it is applicable, unit-compatible and separated from the next candidate by a visible gap.
    """
    if not candidates:
        return {
            "schema": "candidate_selection_v1",
            "status": "not_found",
            "action": "refine_search",
            "selected_code": "",
            "score_gap": None,
            "reason": "по описанию работы не найдено кандидатов",
            "shortlist": [],
        }
    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    gap = None if second is None else round(_f(top.get("score_total")) - _f(second.get("score_total")), 2)
    top_ok = top.get("applicability_status") == "accepted" and top.get("unit_compatible") is not False
    clear_lead = second is None or (gap is not None and gap >= 2.0)
    if top_ok and clear_lead:
        status = "clear"
        action = "bind_top_candidate"
        selected = str(top.get("norm_code") or "")
        reason = (
            "лидер применим и заметно сильнее ближайшей альтернативы"
            if second else "единственный применимый кандидат"
        )
    elif top_ok:
        status = "needs_model_choice"
        action = "ask_model_to_choose_or_request_input"
        selected = ""
        reason = "есть применимый лидер, но отрыв от альтернатив мал"
    else:
        status = "needs_model_choice"
        action = "ask_model_to_choose_or_request_input"
        selected = ""
        reason = "верхний кандидат не прошёл применимость или единицу измерения"
    return {
        "schema": "candidate_selection_v1",
        "status": status,
        "action": action,
        "selected_code": selected,
        "score_gap": gap,
        "reason": reason,
        "top_reasons": _candidate_reason_labels(top),
        "shortlist": _candidate_shortlist(candidates),
    }


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


# ── Quality Gate 4: SLOT REQUIREMENTS + FORMULA CATALOG ──────────────────────────────────
# Формула НЕ от модели и НЕ придумывает входы. Объём считается из ПОИМЕНОВАННЫХ слотов по
# каталогу под element_type. Нет критичного слота (глубина/толщина/геометрия стен) → needs_input,
# не считаем. Слоты: из геометрии (S,N,S1,P,H — авто) + от пользователя + допущения (where can).

# element_type → {unit, expr над слотами, required(критичные), assume(slot→дефолт или geom-var)}.
FORMULA_CATALOG: dict[str, dict[str, Any]] = {
    "excavation": {
        "unit": "м3", "expr": "S1 * excavation_depth_m * overdig_factor",
        "required": ["excavation_depth_m"], "assume": {"overdig_factor": 1.2}},
    "concrete_preparation": {
        "unit": "м3", "expr": "S1 * prep_thickness_m",
        "required": [], "assume": {"prep_thickness_m": 0.1}},
    "foundation_slab": {
        "unit": "м3", "expr": "slab_area_m2 * slab_thickness_m",
        "required": ["slab_thickness_m"], "assume": {"slab_area_m2": "S1"}},
    "monolithic_slab": {
        "unit": "м3", "expr": "floor_area_m2 * slab_thickness_m * N",
        "required": ["slab_thickness_m"], "assume": {"floor_area_m2": "S1"}},
    "monolithic_wall": {
        "unit": "м3", "expr": "wall_length_m * wall_height_m * wall_thickness_m",
        "required": ["wall_length_m", "wall_height_m", "wall_thickness_m"], "assume": {}},
    "waterproofing": {
        "unit": "м2", "expr": "P * H * N + S1",   # стены + дно, из геометрии — считаемо
        "required": [], "assume": {}},
}


def _is_number(v: Any) -> bool:
    try:
        float(str(v).replace(",", ".").replace(" ", ""))
        return True
    except (TypeError, ValueError):
        return False


def resolve_slots(element_type: str, geom: dict[str, Any], user_slots: dict[str, Any]
                  ) -> tuple[dict | None, dict, list[str], list[str]]:
    """Слоты под element_type: геометрия + пользователь + допущения. Возвращает
    (spec, namespace, missing_critical, assumptions_used). Нет spec → (None,…)."""
    spec = FORMULA_CATALOG.get(element_type)
    if not spec:
        return None, {}, [], []
    ns: dict[str, float] = {k: _f(v) for k, v in (geom or {}).items()}
    for k, v in (user_slots or {}).items():
        if _is_number(v):
            ns[k] = _f(v)
    assumptions: list[str] = []
    for slot, default in spec.get("assume", {}).items():
        if slot in ns:
            continue
        val = ns.get(default) if (isinstance(default, str) and default in ns) else (_f(default) if _is_number(default) else None)
        if val is not None:
            ns[slot] = val
            assumptions.append(f"{slot}={round(val, 3)} (допущение)")
    missing = [s for s in spec.get("required", []) if s not in ns]
    return spec, ns, missing, assumptions


_PARAM_PATTERNS = [
    ("excavation_depth_m", r"глубин\w*\D{0,18}(\d+(?:[.,]\d+)?)\s*м(?!\w)", 1.0),
    ("slab_thickness_m",   r"(?:плит\w*|фундамент\w*)\D{0,16}(\d+(?:[.,]\d+)?)\s*(мм|см|м)\b", None),
    ("wall_thickness_m",   r"стен\w*\D{0,16}(\d+(?:[.,]\d+)?)\s*(мм|см|м)\b", None),
    ("wall_height_m",      r"высот\w*\D{0,14}(\d+(?:[.,]\d+)?)\s*м(?!\w)", 1.0),
    ("wall_length_m",      r"(?:периметр|длин\w* стен)\D{0,14}(\d+(?:[.,]\d+)?)\s*м(?!\w)", 1.0),
]


def parse_params(question: str) -> dict[str, float]:
    """Достать известные параметры из текста запроса → слоты (для петли уточнения в одном
    запросе: «паркинг 4800 глубина 6м плита 400мм»). Мм/см → метры."""
    ql = (question or "").lower()
    slots: dict[str, float] = {}
    for slot, pat, _mult in _PARAM_PATTERNS:
        m = re.search(pat, ql)
        if not m:
            continue
        val = _f(m.group(1))
        unit = (m.group(2) if m.lastindex and m.lastindex >= 2 else "м")
        if unit == "мм":
            val /= 1000.0
        elif unit == "см":
            val /= 100.0
        slots[slot] = val
    return slots


# ── планировщик ──────────────────────────────────────────────────────────────────────────

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
    "\"unit_hint\":\"м3|м2\"}} — кандидаты ГЭСН + selection. Если selection.action="
    "bind_top_candidate, можно брать selected_code; иначе выбери из shortlist или спроси данные.\n"
    "3) {\"tool\":\"add_position\",\"args\":{\"work\":\"..\",\"code\":\"NN-NN-NNN-NN\","
    "\"work_family\":\"..\",\"element_type\":\"<из списка>\",\"slots\":{\"slab_thickness_m\":0.4,..}}} "
    "— объём считает КОД по element_type (формула в каталоге, НЕ ты). Слоты: что знаешь "
    "(толщина/глубина/геометрия стен). Нет критичного слота → needs_input (НОРМАЛЬНО, не выдумывай; "
    "это сигнал спросить пользователя). Геометрия (S,S1,P,H) подставляется сама.\n"
    "4) {\"final\":true} — собрать (ПРЕДВАРИТЕЛЬНО).\n\n"
    "Подземный паркинг: котлован(earthworks), гидроизоляция(waterproofing), фунд.плита+стены+"
    "перекрытия(concrete_monolithic). Один JSON за ход; коды — только из search_norm."
)

BATCH_SYSTEM_PROMPT = (
    "/no_think\n"
    "Ты инженер-сметчик. Верни только компактный JSON, без markdown и пояснений. "
    "Модель раскладывает объект, но НЕ придумывает коды ГЭСН, объёмы и деньги: это делает код.\n"
    "Формат: {\"object\":{\"object_type\":\"...\",\"area_total_m2\":150,\"floors\":1,"
    "\"levels_below_ground\":0,\"structural_system\":\"...\",\"missing_inputs\":[\"...\"]},"
    "\"works\":[[\"work\",\"search description\",\"family\",\"element\",\"action\",\"unit\",{\"slot\":1}]]}\n"
    "family: earthworks,foundation,concrete_monolithic,concrete_precast,masonry,metal,wood,floors,"
    "roofing,waterproofing,finishes. element: excavation,concrete_preparation,foundation_slab,"
    "monolithic_wall,monolithic_slab,column,waterproofing,roofing,wood_wall,metal_assembly,pile,foundation.\n"
    "Дай 3-6 ключевых работ. work и search description пиши по-русски, словами из строительных норм. "
    "unit только м3, м2 или т. missing_inputs максимум 5. Если параметра нет, не выдумывай slot. "
    "Коды норм не включай."
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
    # Gate 4: объём из FORMULA CATALOG по element_type + СЛОТЫ (формула НЕ от модели и НЕ
    # придумывает входы). Нет критичного слота (глубина/толщина/геометрия стен) → needs_input.
    et = str(args.get("element_type", ""))
    user_slots = {**state.get("user_slots", {}), **(args.get("slots") or {})}
    if et in FORMULA_CATALOG:
        spec, ns, missing, slot_assumptions = resolve_slots(et, state["geom"], user_slots)
        if missing:
            state["positions"].append({**base_pos, "status": "needs_input", "missing_slots": missing,
                                       "reason": f"нет параметров: {', '.join(missing)}"})
            return {"ok": True, "status": "needs_input", "missing_slots": missing,
                    "reason": f"для расчёта нужны: {', '.join(missing)} — спроси пользователя"}
        try:
            phys = _eval_formula(spec["expr"], ns)
        except Exception as e:  # noqa: BLE001
            state["positions"].append({**base_pos, "status": "needs_input", "reason": str(e)[:80]})
            return {"ok": True, "status": "needs_input", "reason": str(e)[:80]}
        base_pos["physical_unit"] = _canon_unit(spec["unit"])      # единица из каталога, не от модели
        base_pos["assumptions"] = list(base_pos.get("assumptions", [])) + slot_assumptions
        base_pos["formula"] = spec["expr"]
    else:
        # legacy: element_type вне каталога → принимаем qty_formula модели (всё ещё через Gate 1)
        try:
            phys = _eval_formula(str(args.get("qty_formula", "")), state["geom"])
        except Exception as e:  # noqa: BLE001
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


def _as_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, dict)]


def _schema_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    schema = plan.get("object") or plan.get("object_schema") or plan.get("schema") or {}
    return schema if isinstance(schema, dict) else {}


def _coerce_work_item(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, (list, tuple)) or len(value) < 6:
        return None
    slots = value[6] if len(value) >= 7 and isinstance(value[6], dict) else {}
    return {
        "work": value[0],
        "work_description": value[1],
        "work_family": value[2],
        "element_type": value[3],
        "action": value[4],
        "unit_hint": value[5],
        "slots": slots,
    }


def _work_items_from_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    raw = plan.get("works") if "works" in plan else plan.get("work_items")
    items: list[dict[str, Any]] = []
    for value in raw if isinstance(raw, list) else []:
        item = _coerce_work_item(value)
        if item:
            items.append(item)
    return items


def _candidate_codes(candidates: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    codes: list[str] = []
    for c in candidates[:limit]:
        code = str(c.get("norm_code") or "").strip()
        if code:
            codes.append(code)
    return codes


def _append_unbound_position(item: dict[str, Any], search: dict[str, Any],
                             state: dict[str, Any]) -> None:
    candidates = _as_items(search.get("candidates"))
    top = candidates[0] if candidates else {}
    selection = search.get("selection") if isinstance(search.get("selection"), dict) else {}
    status = "ambiguous" if candidates else "needs_input"
    reason = (
        "нет уверенно применимой нормы ГЭСН"
        if candidates else "норма ГЭСН не найдена по описанию работы"
    )
    if search.get("status") == "not_found":
        reason = str(search.get("hint") or reason)
    state["positions"].append({
        "work": item.get("work") or item.get("work_description") or "",
        "code": top.get("norm_code", ""),
        "work_family": item.get("work_family", ""),
        "physical_unit": _canon_unit(item.get("unit_hint", "")),
        "status": status,
        "reason": reason,
        "candidates": candidates[:5],
        "selection": selection,
    })


def _run_batch_plan(question: str, complete: Callable[[list[dict[str, str]]], str],
                    state: dict[str, Any], *, max_steps: int = 16) -> dict[str, Any]:
    _slots_note = (f"Известные параметры из текста: {state.get('user_slots')}."
                   if state.get("user_slots") else
                   "Если параметров нет, оставь missing_inputs/пустые slots; код не будет выдумывать.")
    messages = [
        {"role": "system", "content": BATCH_SYSTEM_PROMPT},
        {"role": "user", "content": f"Объект/контекст:\n{question}\n\n{_slots_note}"},
    ]
    state["steps"] = 1
    raw = complete(messages) or ""
    plan = _extract_json(raw)
    trace: list[dict[str, Any]] = []

    if plan is None:
        res = _finalize(state, note="модель не вернула машинный JSON-план")
        res["trace"] = trace
        res["planner_status"] = "no_json"
        return res

    # Совместимость с прежним tool-loop контрактом: если модель вернула один tool-call,
    # исполняем старый режим, но только как fallback, не как основной прод-путь.
    if plan.get("tool") or plan.get("final"):
        return _run_tool_loop(question, complete, state=state, max_steps=max_steps,
                              first_call=plan, first_raw=raw)

    schema = _schema_from_plan(plan)
    obs_schema = _exec_tool("propose_schema", schema, state)
    trace.append({"tool": "propose_schema",
                  "status": "ok" if obs_schema.get("ok") else "err",
                  "missing_inputs": obs_schema.get("missing_inputs")
                  or obs_schema.get("missing_required") or []})

    for raw_item in _work_items_from_plan(plan):
        item, corrections = _normalize_work_item(raw_item)
        search_args = {
            "work_description": str(item.get("work_description") or item.get("work") or ""),
            "work_family": str(item.get("work_family") or ""),
            "element_type": str(item.get("element_type") or ""),
            "action": str(item.get("action") or ""),
            "unit_hint": str(item.get("unit_hint") or ""),
        }
        search = _exec_tool("search_norm", search_args, state)
        candidates = _as_items(search.get("candidates"))
        trace.append({
            "tool": "search_norm",
            "status": search.get("status") or ("ok" if search.get("ok") else "err"),
            "work": item.get("work") or item.get("work_description") or "",
            "candidates": _candidate_codes(candidates),
            "selection": search.get("selection", {}),
            "normalized": corrections,
        })
        top = candidates[0] if candidates else None
        if search.get("status") == "found" and top and top.get("unit_compatible") is not False:
            add_args = {
                "work": item.get("work") or item.get("work_description") or top.get("title") or "",
                "code": top.get("norm_code", ""),
                "work_family": item.get("work_family") or search.get("work_family") or "",
                "element_type": item.get("element_type") or search.get("element_type") or "",
                "slots": item.get("slots") if isinstance(item.get("slots"), dict) else {},
            }
            obs = _exec_tool("add_position", add_args, state)
            trace.append({"tool": "add_position",
                          "status": obs.get("status") or ("ok" if obs.get("ok") else "err"),
                          "work": add_args["work"],
                          "code": add_args["code"]})
        else:
            _append_unbound_position(item, search, state)

    res = _finalize(state)
    res["trace"] = trace
    res["planner_status"] = "batch"
    return res


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


def _run_tool_loop(question: str, complete: Callable[[list[dict[str, str]]], str],
                   *, state: dict[str, Any], max_steps: int = 16,
                   first_call: dict[str, Any] | None = None, first_raw: str = "") -> dict[str, Any]:
    user_slots = state.get("user_slots", {})
    _slots_note = (f" Известные параметры: {user_slots}." if user_slots else
                   " Параметры (глубина/толщины/геометрия стен) НЕ заданы — где их нет, позиция станет needs_input.")
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Объект: {question}\nНачни с propose_schema.{_slots_note}"},
    ]
    trace: list[dict[str, Any]] = []
    pending_call = first_call
    pending_raw = first_raw
    for _ in range(max_steps):
        state["steps"] += 1
        if pending_call is not None:
            call = pending_call
            raw = pending_raw
            pending_call = None
            pending_raw = ""
        else:
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


def run_estimate_harness(question: str, complete: Callable[[list[dict[str, str]]], str],
                         *, max_steps: int = 16) -> dict[str, Any]:
    # Gate 4: параметры из запроса → слоты (уточнение в одном запросе:
    # «… глубина 6м плита 400мм»).
    user_slots = parse_params(question)
    state: dict[str, Any] = {"schema": {}, "geom": {}, "positions": [], "steps": 0,
                             "user_slots": user_slots}
    return _run_batch_plan(question, complete, state, max_steps=max_steps)


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
