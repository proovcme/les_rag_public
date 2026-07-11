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
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from proxy.services.candidate_selection_service import (
    candidate_reason_labels,
    candidate_shortlist,
    select_candidates,
)
from proxy.services.estimate_math_service import _eval_formula, _f, _geometry
from proxy.services.notebook_service import gesn_notebook_prompt_excerpt
from proxy.services.prompt_registry_service import build_smeta_batch_system_prompt
from proxy.services.smeta_norm_store import get_smeta_norm_store, norm_store_payload


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

# ── единицы измерения (UNIT CONTRACT) ────────────────────────────────────────────────────

_COUNT_UNIT_PREFIXES = (
    "шт", "штук", "компл", "комплект", "узел", "точ", "порт", "мест", "стык", "соедин",
    "издел", "элемент", "прибор", "аппарат", "датчик", "насад", "розет", "шкаф",
    "панел", "модул", "люк", "коробк", "кассет", "адаптер", "пигтейл", "разъем", "разъём",
)


def _canon_unit(u: str) -> str:
    """Канонизировать единицу: м³/м²/куб.м → м3/м2; нижний регистр; без пробелов."""
    s = (u or "").strip().lower().replace("³", "3").replace("²", "2")
    s = s.replace("куб.м", "м3").replace("кв.м", "м2").replace("куб м", "м3").replace("кв м", "м2")
    s = re.sub(r"\s+", "", s)
    s = s.replace("п.м.", "м").replace("п.м", "м").replace("м.п.", "м").replace("м.п", "м")
    s = re.sub(r"^\d+(?=[а-яa-z])", "", s).strip(".,;:")
    aliases = {
        "мп": "м", "пм": "м", "метр": "м", "метры": "м", "meters": "м", "meter": "м",
        "piece": "шт", "pcs": "шт", "pc": "шт",
    }
    if s in aliases:
        return aliases[s]
    if s == "км" or s.startswith(("кмкаб", "кмтруб", "кмтрас", "кмпути", "кмсет")):
        return "км"
    for base in ("м3", "м2"):
        if s == base or s.startswith(base + ".") or s.startswith(base):
            return base
    if s == "м" or s.startswith("м.") or s.startswith((
        "мкаб", "мтруб", "млот", "мкороб", "мшв", "мпровод", "мтрас", "мсет", "мканал", "мжелоб", "мрукав",
    )):
        return "м"
    if s.startswith(_COUNT_UNIT_PREFIXES):
        return "шт"
    if s == "т" or s.startswith(("тметалл", "тконструк", "тстали", "тарматур", "тиздел")):
        return "т"
    if s.startswith(("тонн", "kg", "кг")):
        return "т" if s.startswith("тонн") else "кг"
    return s


def _norm_unit_factor(unit: str) -> tuple[float, str]:
    """Измеритель нормы → (множитель, базовая единица). «100 м3»→(100,«м3»); «10 м2»→(10,«м2»);
    «м3»→(1,«м3»); «т»→(1,«т»)."""
    m = re.match(r"\s*(\d+)?\s*(.+)", str(unit or "").strip())
    if not m:
        return 1.0, _canon_unit(unit)
    factor = float(m.group(1)) if m.group(1) else 1.0
    return factor, _canon_unit(m.group(2))


def _units_compatible(physical_unit: str, norm_base_unit: str) -> bool:
    return _unit_conversion_factor(physical_unit, norm_base_unit) is not None


def _unit_conversion_factor(physical_unit: str, norm_base_unit: str) -> float | None:
    """Multiplier to convert physical quantity into norm base unit before norm factor division."""
    src = _canon_unit(physical_unit)
    dst = _canon_unit(norm_base_unit)
    if src == dst:
        return 1.0
    table = {
        ("м", "км"): 0.001,
        ("км", "м"): 1000.0,
        ("кг", "т"): 0.001,
        ("т", "кг"): 1000.0,
    }
    return table.get((src, dst))


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
    "floors": "floors",
    "finishes": "finishes",
    "finish": "finishes",
    "cable": "electric",
    "pipe": "electric",
    "box": "electric",
    "fastener": "electric",
    "device": "electric",
    "backup_power": "electric",
    "light": "electric",
    "hatch": "finishes",
    "primer": "finishes",
    "putty": "finishes",
    "wallpaper": "finishes",
    "painting": "finishes",
    "ceiling": "finishes",
    "engineering_networks": "mep",
}

_ACTION_ALIASES: dict[str, str] = {
    "assemble": "монтаж",
    "assembly": "монтаж",
    "disassemble": "демонтаж",
    "dismantle": "демонтаж",
    "demount": "демонтаж",
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
    "m": "м",
    "meter": "м",
    "meters": "м",
    "м": "м",
    "мп": "м",
    "пм": "м",
    "t": "т",
    "ton": "т",
    "tons": "т",
    "tonne": "т",
    "tonnes": "т",
    "piece": "шт",
    "pcs": "шт",
    "шт": "шт",
}

_DIRECT_QTY_SLOT_BY_UNIT = {
    "м3": "volume_m3",
    "м2": "area_m2",
    "м": "length_m",
    "т": "mass_t",
    "шт": "piece_count",
    "": "piece_count",
}
_DIRECT_QTY_SLOTS = frozenset(_DIRECT_QTY_SLOT_BY_UNIT.values())
_CALCULATOR_SAFE_GLOBAL_SLOTS = frozenset({
    "excavation_depth_m",
    "slab_thickness_m",
    "wall_thickness_m",
    "wall_height_m",
    "wall_length_m",
    "pile_count",
    "soil_group",
})

_SMETA_REASON_LABELS: dict[str, tuple[str, str]] = {
    "collection": ("сборник соответствует семейству работ", "сборник не соответствует семейству работ"),
    "unit": ("единица измерения совпадает", "единица измерения не совпадает"),
    "element": ("есть признаки нужного элемента", "есть признаки другого элемента"),
    "family": ("есть признаки семейства работ", "нет признаков семейства работ"),
    "action": ("совпало действие работы", "действие работы не совпало"),
    "route": ("попало в навигацию по разделу/семейству", ""),
    "forbidden": ("", "есть признаки специальной/неподходящей нормы"),
    "denied_subsection": ("", "подраздел не подходит для семейства работ"),
    "action_conflict": ("", "действие нормы явно противоречит исходной операции"),
}

def _collection_of(code: str) -> str:
    m = re.search(r"(?<!\d)(\d{2})-\d{2}-\d{3}-\d{2}", str(code or ""))
    return m.group(1) if m else ""


def _base_type_of(code: str) -> str:
    s = str(code or "").strip()
    if s.startswith("ГЭСНм"):
        return "ГЭСНм"
    if s.startswith("ГЭСНр"):
        return "ГЭСНр"
    if s.startswith("ГЭСНп"):
        return "ГЭСНп"
    return "ГЭСН"


def _collection_key(code: str) -> str:
    collection = _collection_of(code)
    base_type = _base_type_of(code)
    if base_type == "ГЭСН" or not collection:
        return collection
    return f"{base_type}{collection}"


def _plain_norm_code(code: str) -> str:
    """Return the bare numeric identity without inferring or changing its family."""
    match = re.search(r"(?<!\d)(\d{2}-\d{2}-\d{3}-\d{2})", str(code or ""))
    return match.group(1) if match else ""


_ELEMENT_TEXT_SIGNALS: tuple[tuple[str, str, str], ...] = (
    ("engineering_networks", "mep", r"\b(?:инженерн\w*\s+(?:сет|систем)|сет\w*\s+инженер|вк\b|ов\b|эом\b|сс\b|водопровод|канализац|отоплен|вентиляц|электр|кабел|слаботоч)"),
    ("metal_assembly", "metal", r"\b(?:металлоконструкц|металл\w*|стальн\w*|сталь|листов\w*\s+конструкц)"),
    ("wood_wall", "wood", r"\b(?:дерев|брус|бревн|каркасно[- ]?щит|каркасн\w*\s+стен|стен\w*\s+каркас)"),
    ("roofing", "roofing", r"\b(?:кровл|стропил|двускат|плоск\w*\s+кров)"),
    ("excavation", "earthworks", r"\b(?:котлован|грунт|транше|выемк|землян|разработк)"),
    ("pile", "foundation", r"\b(?:сва|ростверк|свайн)"),
    ("waterproofing", "waterproofing", r"\b(?:гидроизол|изоляц|обмазочн|оклеечн)"),
    ("foundation_slab", "concrete_monolithic", r"\b(?:фундаментн\w*\s+плит|плитн\w*\s+фундамент)"),
    ("monolithic_wall", "concrete_monolithic", r"\b(?:монолитн\w*\s+стен|бетонирован\w*\s+стен)"),
    ("floors", "floors", r"\b(?:пол|стяжк)"),
    ("finishes", "finishes", r"\b(?:отделк|штукатур|окрас|облицов)"),
)


def _normalize_action(action: str) -> str:
    a = (action or "").strip().lower()
    return _ACTION_ALIASES.get(a, action)


def _normalize_unit_hint(unit: str) -> str:
    u = _canon_unit(unit)
    return _UNIT_ALIASES.get(u, u if u in {"м3", "м2", "м", "т", "шт"} else "")


_OPTIONAL_WORK_RE = re.compile(
    r"\b(?:если\s+требуется|при\s+необходимости|опциональн\w*|уточнить\s+дол\w*|"
    r"уточнить\s+об[ъь]е[мё]\w*|требует\s+уточнен\w*)\b",
    re.IGNORECASE,
)

_DIRECT_OPERATION_SIGNALS: tuple[tuple[str, str], ...] = (
    ("промежуточная разборка", "промежуточн\\w*\\s+разборк"),
    ("разборка", "разборк|демонтаж|демонт"),
    ("контрольная сборка", "контрольн\\w*\\s+сборк"),
    ("укрупнительная сборка", "укрупнительн\\w*\\s+сборк"),
    ("упаковка", "упаковк|транспортировочн\\w*\\s+тар"),
    ("монтаж на площадке", "монтаж.*(?:площадк|месте|объект|стройплощадк)"),
    ("монтаж", "монтаж|установк"),
    ("сварочные работы", "сварочн|сварк"),
    ("погрузочно-разгрузочные работы", "погруз|разгруз|складирован"),
)


def _direct_operation_key(work: str) -> str:
    text = (work or "").casefold().replace("ё", "е")
    for key, pattern in _DIRECT_OPERATION_SIGNALS:
        if re.search(pattern, text):
            return key
    return ""


def _is_optional_direct_work(work: str) -> bool:
    return bool(_OPTIONAL_WORK_RE.search((work or "").casefold().replace("ё", "е")))


def _normalize_work_item(item: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Нормализовать tool-аргументы модели перед поиском ГЭСН.

    Модель отвечает за смысловые поля work_family/element_type. Harness не переписывает их по
    regex-сигналам: он только нормализует машинные алиасы action/unit_hint, чтобы калькулятор и
    поиск получили канонические единицы и действие.
    """
    norm = dict(item)
    corrections: list[str] = []

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


def _work_item_intent_hints(item: dict[str, Any]) -> list[str]:
    """Non-binding trace hints for model/operator review; never used for calculation/search args."""
    hints: list[str] = []
    text = f"{item.get('work', '')} {item.get('work_description', '')}".lower()
    family = str(item.get("work_family") or "")
    element = str(item.get("element_type") or "")
    for inferred_element, inferred_family, pattern in _ELEMENT_TEXT_SIGNALS:
        if not re.search(pattern, text):
            continue
        if element != inferred_element:
            hints.append(f"text suggests element_type={inferred_element}, model sent {element or '—'}")
        if family != inferred_family:
            hints.append(f"text suggests work_family={inferred_family}, model sent {family or '—'}")
        break
    default_family = _ELEMENT_DEFAULT_FAMILY.get(element)
    if default_family and family and family != default_family:
        hints.append(f"element_type={element} usually belongs to work_family={default_family}, model sent {family}")
    return hints


def search_norm(work_description: str, *, work_family: str = "", element_type: str = "",
                action: str = "", unit_hint: str = "", top_k: int = 6) -> dict[str, Any]:
    """Universal norm retrieval. It returns cards; model/user owns applicability and choice."""
    if not str(work_description or "").strip():
        return {"status": "not_found", "candidates": [], "missing_inputs": ["work_description"]}
    from proxy.smeta_core.norm_browser import browse_norms

    uh = _canon_unit(unit_hint)
    browse = browse_norms(work_description, limit=max(top_k, 1))
    cards = list(browse.get("cards") or [])
    if not cards:
        return {"status": "not_found", "candidates": [], "hint": "переформулируй work_description"}
    candidates: list[dict[str, Any]] = []
    for rank, card in enumerate(cards[:top_k], 1):
        c = str(card.get("norm_code") or "")
        nm = str(card.get("title") or "")
        u = str(card.get("measure_unit") or "")
        factor, base = _norm_unit_factor(u)
        candidates.append({"norm_code": c, "title": nm, "collection": _collection_of(c),
                           "measure_unit": u, "base_unit": base,
                           "unit_compatible": (not uh) or _units_compatible(uh, base),
                           "applicability_status": "model_review_required", "rejection_reasons": [],
                           "score_total": float(max(top_k - rank + 1, 1)),
                           "score_parts": {"retrieval_rank": rank},
                           "norm_profile": card})
    selection = _candidate_selection(candidates)
    navigation = _search_norm_navigation(candidates, work_family=work_family, element_type=element_type, unit_hint=uh)
    return {"status": "ambiguous", "work_family": work_family, "element_type": element_type,
            "norm_store": {"backend": browse.get("backend"), "source_integrity": browse.get("source_integrity")},
            "candidate_pool": {"searched": len(cards), "scored": len(candidates)},
            "norm_navigation": navigation,
            "candidates": candidates, "selection": selection}


def direct_smeta_norm_search_context(question: str, *, limit: int = 8, candidates_per_probe: int = 4) -> str:
    """Generic model-facing norm cards from the actual query; no case-specific decomposition."""
    del candidates_per_probe
    from proxy.smeta_core.norm_browser import browse_norms

    result = browse_norms(question, limit=limit)
    cards = list(result.get("cards") or [])
    if not cards:
        return ""
    lines = [
        "Карточки универсального нормативного поиска ЛЕС по фактическому тексту запроса.",
        "Это не расчёт и не выбранные нормы: модель должна выбрать кандидата или оставить missing.",
        f"Backend: {result.get('backend')}; source integrity: {(result.get('source_integrity') or {}).get('status')}.",
        "Шифр нормы копируй буквально. Применимость выбирает модель по составу работ и условиям источника.",
    ]
    for idx, card in enumerate(cards[:limit], start=1):
        steps = "; ".join(str(item) for item in (card.get("work_steps") or [])[:5])
        lines.append(
            f"{idx}. {card.get('norm_code')} | {card.get('measure_unit')} | "
            f"{str(card.get('title') or '')[:180]} | состав: {steps or 'не извлечён'} | "
            f"source: {card.get('source_ref') or 'navigation only'}"
        )
    return "\n".join(lines)[:12000]


def _search_norm_navigation(candidates: list[dict[str, Any]], *, work_family: str,
                            element_type: str, unit_hint: str) -> dict[str, Any]:
    collections: dict[str, dict[str, Any]] = {}
    questions: list[str] = []
    accepted = 0
    unit_mismatch = 0
    for candidate in candidates:
        profile = candidate.get("norm_profile") if isinstance(candidate.get("norm_profile"), dict) else {}
        nav = profile.get("navigation") if isinstance(profile.get("navigation"), dict) else {}
        collection = nav.get("collection") if isinstance(nav.get("collection"), dict) else {}
        key = str(collection.get("key") or candidate.get("collection") or "")
        if key:
            bucket = collections.setdefault(key, {"key": key, "label": collection.get("label") or key, "count": 0})
            bucket["count"] += 1
        for question in nav.get("questions_to_ask") or []:
            text = str(question or "").strip()
            if text and text not in questions:
                questions.append(text)
        if candidate.get("applicability_status") == "accepted" and candidate.get("unit_compatible"):
            accepted += 1
        if candidate.get("unit_compatible") is False:
            unit_mismatch += 1
    if accepted:
        next_step = "можно брать выбранную применимую норму в расчёт, но проверить условия нормы"
    elif unit_mismatch:
        next_step = "сначала уточнить физическую единицу/объём: первые найденные нормы не совпадают по измерителю"
    elif candidates:
        next_step = "кандидаты есть, но применимость не уверена: сравнить соседние нормы и спросить условия"
    else:
        next_step = "переформулировать описание работы строительными терминами"
    return {
        "purpose": "карта выбора нормы для модели; не расчёт и не готовый ответ",
        "intent": {
            "work_family": work_family,
            "element_type": element_type,
            "unit_hint": unit_hint,
        },
        "collections": sorted(collections.values(), key=lambda x: (-int(x.get("count") or 0), str(x.get("key"))))[:5],
        "questions_to_ask": questions[:8],
        "next_step": next_step,
        "rim_boundary": "модель выбирает ход и вопросы; add_position/lsr_assembly считают объём, ресурсы, НР/СП и итог",
        "decision_context": _norm_decision_context(candidates),
    }


def _norm_decision_context(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Compact model-facing checklist for choosing a norm from a shortlist."""
    accepted = [
        c for c in candidates
        if c.get("applicability_status") == "accepted" and c.get("unit_compatible") is not False
    ]
    rejected = [
        c for c in candidates
        if c.get("applicability_status") == "rejected" or c.get("unit_compatible") is False
    ]
    ambiguous = [
        c for c in candidates
        if c.get("applicability_status") not in {"accepted", "rejected"}
        and c.get("unit_compatible") is not False
    ]
    checks = [
        "сборник/тип базы соответствует семейству работ",
        "измеритель нормы совместим с физическим объёмом",
        "условия нормы подтверждены текстом, файлом или допущением",
        "соседние нормы просмотрены, если лидер не очевиден",
        "цены ресурсов будут проверены после раскрытия нормы",
    ]
    return {
        "schema": "norm_decision_context_v1",
        "accepted_count": len(accepted),
        "ambiguous_count": len(ambiguous),
        "rejected_count": len(rejected),
        "checks": checks,
        "recommended_action": (
            "model_choose_norm_then_add_position"
            if accepted else
            "ask_or_refine_norm_search" if candidates else "rewrite_work_description"
        ),
    }


def _candidate_reason_labels(candidate: dict[str, Any]) -> list[str]:
    return candidate_reason_labels(candidate, reason_labels=_SMETA_REASON_LABELS)


def _candidate_shortlist(candidates: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    short = candidate_shortlist(candidates, limit=limit, reason_labels=_SMETA_REASON_LABELS)
    for item, candidate in zip(short, candidates[:limit]):
        profile = candidate.get("norm_profile") if isinstance(candidate.get("norm_profile"), dict) else {}
        item["work_steps"] = [str(step) for step in (profile.get("work_steps") or [])[:12]]
        item["source_ref"] = str(profile.get("source_ref") or "")
        item["resource_kinds"] = profile.get("resource_kinds") or {}
    return short


def _candidate_selection(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a visible shortlist, never a code-selected norm binding."""
    selection = select_candidates(candidates, reason_labels=_SMETA_REASON_LABELS)
    selection = dict(selection)
    selection["shortlist"] = _candidate_shortlist(candidates)
    if selection.get("action") == "bind_top_candidate":
        selection = dict(selection)
        selection.update({
            "status": "needs_model_choice",
            "action": "ask_model_to_choose_or_request_input",
            "selected_code": "",
            "reason": "кандидат сильный, но выбор нормы остаётся за моделью-сметчиком",
            "model_first_boundary": (
                "search_norm показывает shortlist и проверки; "
                "add_position считает только выбранную моделью норму"
            ),
        })
    return selection


def _candidate_by_code(candidates: list[dict[str, Any]], code: str) -> tuple[dict[str, Any] | None, int]:
    wanted = str(code or "").strip()
    if not wanted:
        return None, -1
    for index, candidate in enumerate(candidates):
        if str(candidate.get("norm_code") or "").strip() == wanted:
            return candidate, index
    return None, -1


def _candidate_from_checked_model_code(code: str) -> dict[str, Any] | None:
    """Turn an explicit model-selected norm code into a calculator candidate.

    Search shortlist is retrieval/navigation; if the model names a real code that the current
    shortlist missed, the harness may verify the code in the norm store and let add_position run
    the normal collection/applicability/unit/calculation gates. It must not replace that code with
    the first search hit.
    """
    wanted = str(code or "").strip()
    if not wanted:
        return None
    row = get_smeta_norm_store().by_code(wanted)
    if row is None:
        return None
    return {
        "norm_code": row.code,
        "title": row.title,
        "measure_unit": row.measure_unit,
        "score_total": 0.0,
        "score_parts": {"model_selected_code": 1.0},
        "applicability_status": "model_selected_checked",
        "unit_compatible": None,
        "reasons": ["шифр выбран моделью и найден в локальной базе норм"],
        "norm_profile": row.profile(),
        "outside_shortlist": True,
    }


def _model_select_candidate(
    *,
    item: dict[str, Any],
    search: dict[str, Any],
    candidates: list[dict[str, Any]],
    messages: list[dict[str, str]],
    complete: Callable[[list[dict[str, str]]], str],
) -> tuple[dict[str, Any] | None, int, dict[str, Any] | None]:
    """Ask the model to choose from an ambiguous shortlist.

    The model may pick only a returned norm_code or ask for missing inputs. The harness validates
    the selected code against the shortlist; calculation still goes through add_position gates.
    """
    selection = search.get("selection") if isinstance(search.get("selection"), dict) else {}
    if not candidates:
        return None, -1, None

    if not _env_bool("LES_SMETA_MODEL_NORM_CHOICE_ENABLED", True):
        return None, -1, {
            "tool": "model_norm_choice",
            "status": "skipped_weak_candidate",
            "work": item.get("work") or item.get("work_description") or "",
            "selected_code": "",
            "reason": "слабый или неоднозначный shortlist не отправлен во второй LLM-выбор; позиция остаётся в доборе нормы/цен",
            "ask_user": "",
        }

    shortlist = selection.get("shortlist") if isinstance(selection.get("shortlist"), list) else []
    if not shortlist:
        shortlist = _candidate_shortlist(candidates)
    selection_brief = {
        "schema": selection.get("schema", ""),
        "status": selection.get("status", ""),
        "action": selection.get("action", ""),
        "selected_code": selection.get("selected_code", ""),
        "score_gap": selection.get("score_gap"),
        "reason": selection.get("reason", ""),
    }
    choice_messages = list(messages)
    choice_messages.extend([
        {"role": "assistant", "content": json.dumps({
            "work": item.get("work") or item.get("work_description") or "",
            "search_norm": {
                "status": search.get("status"),
                "selection": selection_brief,
                "shortlist": shortlist[:5],
            },
        }, ensure_ascii=False)},
        {"role": "user", "content": (
            "search_norm вернул список норм. Ты сметчик, а код только проверит твой выбор. "
            "Выбери норму только из shortlist, если по запросу/ТЗ понятны работа, единица и условия "
            "применимости; иначе оставь selected_code пустым и задай короткий вопрос пользователю. "
            "Не выбирай норму потому, что она первая в списке. Верни ровно JSON: "
            "{\"selected_code\":\"ГЭСН:.. или пусто\",\"selection_kind\":\"exact|analog\","
            "\"analog_limitations\":[\"отличие аналога\"],\"reason\":\"почему\","
            "\"ask_user\":\"что уточнить или пусто\"}. Для exact analog_limitations пуст; "
            "для analog нужен хотя бы один конкретный предел применимости. Без markdown."
        )},
    ])
    raw = complete(choice_messages) or ""
    choice = _extract_json(raw) or {}
    selected_code = str(choice.get("selected_code") or "").strip()
    chosen, chosen_index = _candidate_by_code(candidates, selected_code)
    if not chosen and selected_code:
        chosen = _candidate_from_checked_model_code(selected_code)
        chosen_index = -1 if chosen else -1
    selection_kind = str(choice.get("selection_kind") or "").strip().casefold()
    analog_limitations = [
        str(item).strip() for item in (choice.get("analog_limitations") or []) if str(item).strip()
    ]
    contract_ok = selection_kind in {"exact", "analog"} and (
        (selection_kind == "analog" and bool(analog_limitations))
        or (selection_kind == "exact" and not analog_limitations)
    )
    if chosen and not contract_ok:
        chosen = None
        chosen_index = -1
    trace = {
        "tool": "model_norm_choice",
        "status": "selected" if chosen else ("needs_input" if choice.get("ask_user") else "invalid"),
        "work": item.get("work") or item.get("work_description") or "",
        "selected_code": str(choice.get("selected_code") or ""),
        "reason": str(choice.get("reason") or ""),
        "ask_user": str(choice.get("ask_user") or ""),
        "selection_kind": selection_kind,
        "is_analog": selection_kind == "analog",
        "analog_limitations": analog_limitations,
        "selection_contract_valid": contract_ok,
    }
    return chosen, chosen_index, trace


def _model_select_candidates_batch(
    *,
    entries: list[dict[str, Any]],
    messages: list[dict[str, str]],
    complete: Callable[[list[dict[str, str]]], str],
) -> dict[int, tuple[dict[str, Any] | None, int, dict[str, Any]]]:
    """Ask the model to choose norms for all work rows in one pass.

    search_norm stays a retrieval/ranking tool. The model decides which shortlist item to bind
    or which missing condition to ask; add_position remains the calculator/checker.
    """
    decisions: dict[int, tuple[dict[str, Any] | None, int, dict[str, Any]]] = {}
    if not entries or not _env_bool("LES_SMETA_BATCH_NORM_CHOICE_ENABLED", False):
        return decisions
    payload_rows: list[dict[str, Any]] = []
    for idx, entry in enumerate(entries):
        candidates = _as_items(entry.get("candidates"))
        if not candidates:
            continue
        search = entry.get("search") if isinstance(entry.get("search"), dict) else {}
        selection = search.get("selection") if isinstance(search.get("selection"), dict) else {}
        payload_rows.append({
            "work_index": idx,
            "work": entry.get("item", {}).get("work") or entry.get("item", {}).get("work_description") or "",
            "family": entry.get("item", {}).get("work_family") or "",
            "element": entry.get("item", {}).get("element_type") or "",
            "unit_hint": entry.get("item", {}).get("unit_hint") or "",
            "selection_hint": {
                "status": selection.get("status", ""),
                "action": selection.get("action", ""),
                "score_gap": selection.get("score_gap"),
                "reason": selection.get("reason", ""),
            },
            "shortlist": _candidate_shortlist(candidates),
        })
    if not payload_rows:
        return decisions
    choice_messages = list(messages)
    choice_messages.extend([
        {"role": "assistant", "content": json.dumps({
            "schema": "smeta_norm_choice_batch_v1",
            "rows": payload_rows[:16],
        }, ensure_ascii=False)},
        {"role": "user", "content": (
            "search_norm вернул список норм. Для каждой строки выбери норму только из её shortlist или задай вопрос. "
            "Score и selection_hint — подсказка поиска, не приказ. Не выбирай норму, если работа, "
            "единица или условия применимости не совпадают с исходником. Верни ровно JSON: "
            "{\"choices\":[{\"work_index\":0,\"selected_code\":\"ГЭСН:.. или пусто\","
            "\"selection_kind\":\"exact|analog\",\"analog_limitations\":[\"отличие аналога\"],"
            "\"reason\":\"почему\",\"ask_user\":\"что уточнить или пусто\"}]}. "
            "Для exact список ограничений пуст; для analog непуст. Без markdown."
        )},
    ])
    raw = complete(choice_messages) or ""
    parsed = _extract_json(raw) or {}
    choices = parsed.get("choices") if isinstance(parsed.get("choices"), list) else []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        try:
            work_index = int(choice.get("work_index"))
        except (TypeError, ValueError):
            continue
        if work_index < 0 or work_index >= len(entries):
            continue
        candidates = _as_items(entries[work_index].get("candidates"))
        selected_code = str(choice.get("selected_code") or "").strip()
        chosen, chosen_index = _candidate_by_code(candidates, selected_code)
        if not chosen and selected_code:
            chosen = _candidate_from_checked_model_code(selected_code)
            chosen_index = -1 if chosen else -1
        selection_kind = str(choice.get("selection_kind") or "").strip().casefold()
        analog_limitations = [
            str(item).strip() for item in (choice.get("analog_limitations") or []) if str(item).strip()
        ]
        contract_ok = selection_kind in {"exact", "analog"} and (
            (selection_kind == "analog" and bool(analog_limitations))
            or (selection_kind == "exact" and not analog_limitations)
        )
        if chosen and not contract_ok:
            chosen = None
            chosen_index = -1
        trace = {
            "tool": "model_norm_choice",
            "status": "selected" if chosen else ("needs_input" if choice.get("ask_user") else "invalid"),
            "work": entries[work_index].get("item", {}).get("work")
            or entries[work_index].get("item", {}).get("work_description") or "",
            "selected_code": str(choice.get("selected_code") or ""),
            "reason": str(choice.get("reason") or ""),
            "ask_user": str(choice.get("ask_user") or ""),
            "selection_kind": selection_kind,
            "is_analog": selection_kind == "analog",
            "analog_limitations": analog_limitations,
            "selection_contract_valid": contract_ok,
            "batch": True,
        }
        decisions[work_index] = (chosen, chosen_index, trace)
    return decisions


# ── magnitude guard: грубые порядковые границы ───────────────────────────────────────────

def _magnitude_check(physical_unit: str, qty: float, geom: dict[str, Any]) -> tuple[bool, float | None, str]:
    """Физический объём против грубой верхней границы из геометрии. Ловит порядковый бред
    (1.44 млн м³ на 4800 м²), НЕ придирается к 2×. ok, bound, reason."""
    base = _canon_unit(physical_unit)
    S = _f(geom.get("S")); S1 = _f(geom.get("S1")); N = _f(geom.get("N")) or 1
    if not geom or (base == "м3" and S1 <= 0) or (base == "м2" and S <= 0):
        return True, None, ""
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
# не считаем. Слоты приходят из текста, ВОР/ТЗ, истории или явных model assumptions; кодовая
# геометрия по area_total_m2 выключена по умолчанию и не является источником объёмов.

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
    "wood_wall": {
        "unit": "м2", "expr": "P * H * N",
        "required": [], "assume": {}},
    "metal_assembly": {
        "unit": "т", "expr": "mass_t",
        "required": ["mass_t"], "assume": {}},
    "roofing": {
        "unit": "м2", "expr": "S1 * roof_area_factor",
        "required": [], "assume": {"roof_area_factor": 1.25}},
    "pile": {
        "unit": "шт", "expr": "pile_count",
        "required": ["pile_count"], "assume": {}},
    "floors": {
        "unit": "м2", "expr": "S",
        "required": [], "assume": {}},
    "finishes": {
        "unit": "м2", "expr": "S * finish_area_factor",
        "required": [], "assume": {"finish_area_factor": 2.5}},
}

def _is_number(v: Any) -> bool:
    try:
        float(str(v).replace(",", ".").replace(" ", ""))
        return True
    except (TypeError, ValueError):
        return False


def _formula_default_value(default: Any, ns: dict[str, float]) -> float | None:
    if isinstance(default, str):
        if default == "H_total":
            h = ns.get("H")
            n = ns.get("N") or 1
            return h * n if h else None
        if default in ns:
            return ns.get(default)
        return _f(default) if _is_number(default) else None
    return _f(default) if _is_number(default) else None


def _formula_vars(expr: str) -> set[str]:
    return {
        token for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", str(expr or ""))
        if token not in {"min", "max", "round"}
    }


def resolve_slots(element_type: str, geom: dict[str, Any], user_slots: dict[str, Any],
                  *, allow_defaults: bool = True
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
    if allow_defaults:
        for slot, default in spec.get("assume", {}).items():
            if slot in ns:
                continue
            val = _formula_default_value(default, ns)
            if val is not None:
                ns[slot] = val
                assumptions.append(f"{slot}={round(val, 3)} (допущение)")
    missing = [s for s in spec.get("required", []) if s not in ns]
    for slot in sorted(_formula_vars(str(spec.get("expr") or ""))):
        if slot not in ns and slot not in missing:
            missing.append(slot)
    return spec, ns, missing, assumptions


_NUM_TOKEN = r"\d[\d\s\xa0.,]*"
_PARAM_PATTERNS = [
    ("mass_t",             rf"(?:масс\w*|вес)[^\d]{{0,80}}({_NUM_TOKEN})\s*(кг|т|тонн\w*)\b", None),
    ("volume_m3",          rf"(?:об[ъь][её]м\w*|выработк\w*)[^\d]{{0,50}}({_NUM_TOKEN})\s*(м3|м³|куб\.?\s*м)\b", None),
    ("area_m2",            rf"(?:площад\w*)[^\d]{{0,50}}({_NUM_TOKEN})\s*(м2|м²|кв\.?\s*м)\b", None),
    ("length_m",           rf"(?:длин\w*|протяж[её]нн\w*|трасс\w*|кабел\w*|лотк\w*|короб\w*|труб\w*)[^\d]{{0,50}}({_NUM_TOKEN})\s*(м(?![23²³])|метр\w*|п\.?\s*м\.?|м\.?\s*п\.?)\b", 1.0),
    ("excavation_depth_m", rf"глубин\w*\D{{0,18}}({_NUM_TOKEN})\s*(м(?!\w)|метр\w*)", 1.0),
    ("slab_thickness_m",   rf"(?:плит\w*|фундамент\w*)\D{{0,16}}({_NUM_TOKEN})\s*(мм|см|м)\b", None),
    ("wall_thickness_m",   rf"стен\w*\D{{0,16}}({_NUM_TOKEN})\s*(мм|см|м)\b", None),
    ("wall_height_m",      rf"высот\w*\D{{0,14}}({_NUM_TOKEN})\s*(м(?!\w)|метр\w*)", 1.0),
    ("wall_length_m",      rf"(?:периметр|длин\w* стен)\D{{0,14}}({_NUM_TOKEN})\s*(м(?!\w)|метр\w*)", 1.0),
    ("pile_count",         rf"(?:(?:кол(?:-?во|ичество)\s+)?сва\w*\s*(?:[:=№-]\s*)?({_NUM_TOKEN})(?:\s*шт\.?)?|({_NUM_TOKEN})\s*(?:шт\.?\s*)?сва\w*)", 1.0),
]

_SOIL_GROUP_WORDS: dict[str, int] = {
    "iv": 4, "4": 4, "четв": 4,
    "iii": 3, "3": 3, "трет": 3,
    "ii": 2, "2": 2, "втор": 2,
    "i": 1, "1": 1, "перв": 1,
}


def _parse_text_number(value: str) -> float:
    """Parse numbers as they appear after Office/table conversion.

    Russian ToR files commonly mix spaces, NBSP, comma decimals and dot thousand groups
    (``664 711,12``, ``664.711,12``). Some exports use the inverse English grouping
    (``664,711.12``). This parser is intentionally conservative for extracted numeric
    slots: a single comma or dot stays decimal, while mixed separators are resolved by
    the last separator. That avoids treating every ``1.200`` as either 1.2 or 1200 by
    guesswork.
    """
    s = str(value or "").strip().replace("\xa0", "").replace(" ", "")
    if not s:
        return 0.0
    comma = s.rfind(",")
    dot = s.rfind(".")
    if comma >= 0 and dot >= 0:
        decimal_sep = "," if comma > dot else "."
        thousand_sep = "." if decimal_sep == "," else ","
        return _f(s.replace(thousand_sep, "").replace(decimal_sep, "."))
    if s.count(",") > 1:
        return _f(s.replace(",", ""))
    if s.count(".") > 1:
        return _f(s.replace(".", ""))
    if "," in s:
        head, tail = s.split(",", 1)
        return _f(head + "." + tail)
    return _f(s)


def parse_params(question: str) -> dict[str, float]:
    """Достать известные параметры из текста запроса → слоты (для петли уточнения в одном
    запросе: «паркинг 4800 глубина 6м плита 400мм»). Мм/см → метры."""
    ql = (question or "").lower()
    slots: dict[str, float] = {}
    for slot, pat, _mult in _PARAM_PATTERNS:
        m = re.search(pat, ql)
        if not m:
            continue
        groups = [g for g in m.groups() if g]
        raw_value = next((g for g in groups if re.match(r"^\d", str(g))), "")
        val = _parse_text_number(raw_value)
        unit = next(
            (
                g for g in groups
                if str(g).replace(" ", "") in {
                    "мм", "см", "м", "метр", "метра", "метров",
                    "кг", "т", "м3", "м³", "м2", "м²", "куб.м", "кв.м",
                    "п.м.", "п.м", "м.п.", "м.п",
                }
                or str(g).startswith("тонн")
            ),
            "м",
        )
        unit = str(unit).replace(" ", "")
        if unit == "мм":
            val /= 1000.0
        elif unit == "см":
            val /= 100.0
        elif unit == "кг":
            val /= 1000.0
        slots[slot] = val
    soil_match = re.search(
        r"(?:групп\w*\s+грунт\w*|грунт\w*\s+групп\w*)\s*(?:[:№#-]?\s*)?"
        r"(iv|iii|ii|i|[1-4]|перв\w*|втор\w*|трет\w*|четв\w*)",
        ql.replace("ё", "е"),
    )
    if soil_match:
        key = soil_match.group(1).lower()
        for prefix, value in _SOIL_GROUP_WORDS.items():
            if key.startswith(prefix):
                slots["soil_group"] = float(value)
                break
    return slots


_NORM_CONDITION_QUESTION_LABELS: dict[str, str] = {
    "группа грунта": "группа грунта",
    "глубина": "глубина разработки",
    "крепления": "крепления траншей/котлована",
    "геометрия сечения/ширина": "ширина или площадь сечения",
    "масса элемента": "масса элемента",
    "способ производства работ": "способ производства работ",
    "материал/основание": "материал или основание",
}

_NORM_CONDITION_TEXT_ANCHORS: dict[str, tuple[str, ...]] = {
    "крепления": ("с креплен", "без креплен", "креплен"),
    "геометрия сечения/ширина": ("ширин", "сечени", "площадь сечения"),
    "способ производства работ": ("вручную", "механизирован", "кран", "автомобильн", "экскаватор"),
    "материал/основание": (
        "материал", "основан", "каркас", "дерев", "бетон", "железобетон", "рулон", "мембран",
    ),
}

_NORM_CONDITION_SLOT_MAP: dict[str, tuple[str, ...]] = {
    "группа грунта": ("soil_group",),
    "глубина": ("excavation_depth_m",),
    "масса элемента": ("mass_t",),
}

_NORM_CONDITION_NONBLOCKING = {
    "условия применения",
    "способ производства работ",
    "материал/основание",
}


def _norm_profile_for_code(code: str, norm: dict[str, Any] | None = None) -> dict[str, Any]:
    store = get_smeta_norm_store()
    variants = [str(code or "").strip()]
    bare = _plain_norm_code(code)
    if bare:
        base_type = str((norm or {}).get("base_type") or _base_type_of(str((norm or {}).get("code") or code)))
        variants.extend([f"{base_type}:{bare}", f"ГЭСН:{bare}", f"ГЭСНм:{bare}"])
    for variant in variants:
        if not variant:
            continue
        profile = store.norm_profile(variant)
        if profile:
            return profile
    return {}


def _unresolved_norm_questions(
    profile: dict[str, Any],
    *,
    user_slots: dict[str, Any],
    question_text: str,
) -> list[str]:
    """Return norm applicability questions still not answered by user evidence.

    These are not object templates. They come from the selected norm card and only prevent
    a preliminary computed line from being presented as a final estimate.
    """
    q = (question_text or "").casefold().replace("ё", "е")
    unresolved: list[str] = []
    for condition in profile.get("condition_hints") or []:
        label = str(condition or "").strip()
        if not label or label in _NORM_CONDITION_NONBLOCKING:
            continue
        slots = _NORM_CONDITION_SLOT_MAP.get(label, ())
        if slots and any(slot in user_slots and _is_number(user_slots.get(slot)) for slot in slots):
            continue
        anchors = _NORM_CONDITION_TEXT_ANCHORS.get(label, ())
        if anchors and any(anchor in q for anchor in anchors):
            continue
        human = _NORM_CONDITION_QUESTION_LABELS.get(label, label)
        if human not in unresolved:
            unresolved.append(human)
    return unresolved


def _object_area_from_text(question: str, slots: dict[str, float]) -> float | None:
    """Return object area only when it is present in user/file/history text.

    The planner's JSON schema is not evidence. A model may put ``1`` into
    ``area_total_m2`` just to satisfy a contract; that must not become geometry.
    """
    q = (question or "").casefold().replace("ё", "е")
    m = re.search(
        rf"(?:общая\s+площад\w*|площад\w*\s+(?:объекта|здания|дома|строения|помещения|этажа))"
        rf"[^\d]{{0,50}}({_NUM_TOKEN})\s*(?:метр(?:ов|а)?|м|м2|м²|кв\.?\s*м)\b",
        q,
    )
    if m:
        return _parse_text_number(m.group(1))
    object_area = re.search(
        rf"(?:дом|дач\w*|здани\w*|помещени\w*|объект|паркинг|коттедж|строени\w*)"
        rf"\D{{0,80}}({_NUM_TOKEN})\s*(?:м2|м²|кв\.?\s*м)\b",
        q,
    )
    if object_area:
        return _parse_text_number(object_area.group(1))
    return None


def _assumptions_authorized(question: str) -> bool:
    """True when the user explicitly allowed a scenario estimate by assumptions."""
    q = (question or "").casefold().replace("ё", "е")
    return bool(re.search(
        r"\b(?:придумай|прикинь|предположи|допусти|по\s+допущени[яям]|"
        r"типов(?:ой|ые|ому)|ориентировочн[оаяые]*|сам\s+задай|сам\s+прими|сценари\w*)\b",
        q,
    ))


_ESTIMATE_COST_MARKERS = (
    "сметн", "смету", "смета", "стоимост", "расценк", "посчитай", "рассчитай", "рассчитать",
)
_ESTIMATE_WORK_MARKERS = (
    "работ", "разработк", "устройств", "монтаж", "укладк", "прокладк", "бетонирован", "свар", "демонтаж",
    "грунт", "транше", "котлован", "плит", "кровл", "изоляц",
)
_ESTIMATE_TABLE_LOOKUP_MARKERS = ("найди", "покажи", "выведи", "список", "строк")


def is_explicit_work_estimate_request(question: str) -> bool:
    """Narrow auto-route: a request to price a concrete work item with an explicit quantity.

    This intentionally does not catch broad object estimates ("дом 150 м2") and does not know
    specific objects. It only prevents quantity-priced work requests from falling into table/RAG
    lookup just because the text contains "сметная стоимость" or "работы".
    """
    q = (question or "").casefold().replace("ё", "е")
    if any(m in q for m in _ESTIMATE_TABLE_LOOKUP_MARKERS):
        return False
    has_cost = any(m in q for m in _ESTIMATE_COST_MARKERS)
    has_work = any(m in q for m in _ESTIMATE_WORK_MARKERS)
    has_qty = bool(re.search(rf"(?:об[ъь]ем|выработк|колич|кол-во|площад|масс|длин|протяж|трасс|кабел|лотк|короб|труб)[^\d]{{0,50}}{_NUM_TOKEN}\s*(?:м3|м³|м2|м²|м(?![23²³])|кг|т|тонн|шт|куб\.?\s*м|кв\.?\s*м|п\.?\s*м\.?|м\.?\s*п\.?)\b", q))
    return has_cost and has_work and has_qty


def parse_pricebook_hint(question: str) -> str | None:
    """Extract an installed FGIS price book hint from ToR text.

    This is navigation for the calculator, not evidence. If the matching book is not installed,
    lsr_assembly will fall back to its existing default book behavior.
    """
    ql = (question or "").lower().replace("ё", "е")
    wants_spb = "санкт" in ql or "спб" in ql or "петербург" in ql
    wants_2026_q2 = bool(re.search(r"(?:2|ii)[-\s]*(?:ого|ой|й)?\s*(?:кв|кварт)", ql) and "2026" in ql)
    if not (wants_spb and wants_2026_q2):
        return None
    try:
        from proxy.services import fgis_price_service as fps

        stems = [Path(p).stem for p in fps.available_pricebooks()]
    except Exception:  # noqa: BLE001
        stems = []
    for stem in stems:
        low = stem.lower()
        if "spb" in low and "2026" in low and ("2kv" in low or "q2" in low):
            return stem
    return "spb_2kv2026"


_SLOT_LABELS: dict[str, tuple[str, str]] = {
    "mass_t": ("масса", "т"),
    "volume_m3": ("объём", "м3"),
    "area_m2": ("площадь", "м2"),
    "length_m": ("длина", "м"),
    "piece_count": ("количество", "шт"),
    "excavation_depth_m": ("глубина разработки", "м"),
    "slab_thickness_m": ("толщина плиты", "м"),
    "wall_thickness_m": ("толщина стен", "м"),
    "wall_height_m": ("высота стен", "м"),
    "wall_length_m": ("длина/периметр стен", "м"),
    "pile_count": ("количество свай", "шт"),
    "soil_group": ("группа грунта", ""),
}


def _quantity_candidates_from_slots(slots: dict[str, Any], question: str) -> list[dict[str, Any]]:
    """User-provided quantities with provenance for the model and trace.

    This is not a project-volume extractor. It only turns already parsed user text into
    auditable candidates so the harness can say what quantity was used and where it came from.
    """
    candidates: list[dict[str, Any]] = []
    q = re.sub(r"\s+", " ", str(question or "").strip())
    for slot, value in sorted((slots or {}).items()):
        if not _is_number(value):
            continue
        label, unit = _SLOT_LABELS.get(slot, (slot, ""))
        candidates.append({
            "schema": "quantity_candidate_v1",
            "slot": slot,
            "label": label,
            "value": _f(value),
            "unit": unit,
            "source": "user_text",
            "provenance": "текст запроса",
            "confidence": "high",
            "excerpt": q[:240],
        })
    return candidates


def _calculator_slots_from_user_slots(
    slots: dict[str, Any],
    *,
    explicit_direct_work: bool,
) -> dict[str, Any]:
    """Slots allowed to drive formulas before the model binds a quantity to a work item.

    Raw text extraction is intentionally broad: Office/DOCX/TZ/VOR text can contain many
    quantities from different rows. Outside a narrow direct-work request, direct physical
    quantities are navigation candidates for the model, not global calculator inputs.
    """
    if explicit_direct_work:
        return dict(slots or {})
    if not _env_bool("LES_SMETA_GLOBAL_REGEX_SLOTS_ENABLED", True):
        return {}
    return {
        k: v for k, v in (slots or {}).items()
        if k in _CALCULATOR_SAFE_GLOBAL_SLOTS
    }


def _quantity_candidates_prompt_note(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return ""
    bits: list[str] = []
    for c in candidates[:8]:
        slot = str(c.get("slot") or "")
        value = c.get("value")
        unit = str(c.get("unit") or "")
        if not slot or not _is_number(value):
            continue
        bits.append(f"{slot}={_f(value):g} {unit}".strip())
    if not bits:
        return ""
    return (
        "Кандидаты количеств из текста: " + "; ".join(bits) + ". "
        "В широком ТЗ/ВОР/объектной смете это только карта исходных чисел: "
        "привяжи нужное количество в slots конкретной work-позиции, если оно относится именно к ней."
    )


def _quantity_candidate_by_slot(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(c.get("slot")): c for c in candidates
        if isinstance(c, dict) and str(c.get("slot") or "").strip()
    }


def _smeta_service_source_status() -> dict[str, Any]:
    """Small status summary for the estimating data sources."""
    try:
        from proxy.services.service_source_registry import service_sources

        sources = [
            src for src in service_sources().get("sources", [])
            if src.get("domain") == "smeta"
        ]
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "smeta_service_sources_v1",
            "status": "unknown",
            "message": f"{type(exc).__name__}: {exc}",
            "sources": [],
            "missing_for_full_estimate": ["не удалось проверить служебные источники"],
        }
    missing = [
        {
            "id": src.get("id"),
            "label": src.get("label"),
            "status": src.get("status"),
            "requiredness": src.get("requiredness"),
            "action": src.get("operator_action") or src.get("operator_hint") or "",
        }
        for src in sources
        if str(src.get("status") or "") != "ok"
    ]
    return {
        "schema": "smeta_service_sources_v1",
        "status": "ok" if not missing else "incomplete",
        "sources": [
            {
                "id": src.get("id"),
                "label": src.get("label"),
                "status": src.get("status"),
                "facts": src.get("facts") or {},
                "integrity": src.get("integrity") or {},
            }
            for src in sources
        ],
        "missing_for_full_estimate": missing,
    }


# ── планировщик ──────────────────────────────────────────────────────────────────────────

_REQUIRED_SCHEMA = ("object_type",)

BATCH_TOOL_CONTRACT = (
    "/no_think\n"
    "Это только машинный формат вызова сметных инструментов. Профессиональные решения "
    "о составе работ, допущениях, источниках и применимости бери из JSON role-pack и "
    "ГЭСН-блокнота выше, не из этого формата.\n"
    "Верни только компактный JSON smeta_work_plan_v1, без markdown и пояснений. "
    "Формат: {\"object\":{\"object_type\":\"...\",\"area_total_m2\":150|null,\"floors\":1,"
    "\"levels_below_ground\":0,\"structural_system\":\"...\",\"missing_inputs\":[\"...\"],"
    "\"assumptions\":[\"...\"]},"
    "\"works\":[[\"work\",\"search description\",\"family\",\"element\",\"action\",\"unit\","
    "{\"slot\":1},[\"assumption\"]]]}\n"
    "family: earthworks,foundation,concrete_monolithic,concrete_precast,masonry,metal,wood,floors,"
    "roofing,waterproofing,finishes,mep. element: excavation,concrete_preparation,foundation_slab,"
    "monolithic_wall,monolithic_slab,column,waterproofing,roofing,wood_wall,metal_assembly,pile,"
    "foundation,floors,finishes,engineering_networks.\n"
    "unit только м3, м2, м, т или шт. slots — только известные параметры расчёта. "
    "search_norm не выбирает норму за тебя: он возвращает shortlist, проверки и вопросы. "
    "Ты сам выбираешь norm_code из candidates или оставляешь позицию на уточнение. "
    "search description должен содержать ключевые параметры, которые влияют на поиск нормы "
    "(например: масса 10 т, объём 200 м3, грунт 1 группы, глубина 1.5 м), если они есть в тексте "
    "или приняты как допущение. "
    "Для объектных/сценарных расчётов модель сама заполняет числовые slots под формулы: "
    "S (общая площадь), S1 (площадь этажа/пятна), P (периметр), H (высота этажа), N (этажи), "
    "excavation_depth_m, overdig_factor, prep_thickness_m, slab_area_m2, slab_thickness_m, "
    "floor_area_m2, wall_length_m, wall_height_m, wall_thickness_m, roof_area_factor, "
    "finish_area_factor, mass_t, volume_m3, area_m2, length_m, piece_count, pile_count. "
    "Код не придумывает геометрию из area_total_m2 по умолчанию: если это допущение, запиши "
    "его в slots и assumptions. "
    "Если пользователь разрешил сценарий словами «придумай», «прикинь» или «по допущениям», "
    "не отказывайся только потому, что нет проекта/ВОР/РД: выбери условное здание/участок работ "
    "по допущениям, заполни slots и пометь assumptions. "
    "Не передавай qty_formula как способ расчёта: произвольные формулы модели по умолчанию "
    "не исполняются. "
    "missing_inputs и assumptions — массивы строк. Коды норм, деньги, ресурсы и итоговые суммы "
    "в план не включай."
)

BATCH_SYSTEM_PROMPT = build_smeta_batch_system_prompt(BATCH_TOOL_CONTRACT, notebook_context="")


def _add_position(args: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Quality Gate 1: формула→физ.объём → проверки (применимость/единицы/магнитуда) → перевод
    в измеритель нормы. Любой провал → позиция помечается, в итог критичное НЕ идёт."""
    from proxy.services.gesn_service import get_norm

    et = str(args.get("element_type", ""))
    code = str(args.get("code", "")).strip()
    family = str(args.get("work_family", ""))
    base_pos = {"work": args.get("work", ""), "code": code, "work_family": family,
                "physical_unit": _canon_unit(args.get("physical_unit", "")),
                "assumptions": list(args.get("assumptions", []) or []),
                "selection_kind": str(args.get("selection_kind") or ""),
                "is_analog": bool(args.get("is_analog")),
                "analog_limitations": list(args.get("analog_limitations") or []),
                "selection_reason": str(args.get("selection_reason") or "")}
    operation_key = _direct_operation_key(str(base_pos.get("work") or ""))
    if operation_key:
        base_pos["operation_key"] = operation_key
    spec_hint = FORMULA_CATALOG.get(et)
    user_slots = {**state.get("user_slots", {}), **(args.get("slots") or {})}
    norm = get_norm(code)

    if norm is None:
        state["positions"].append({**base_pos, "status": "rejected_norm", "reason": "кода нет в базе ГЭСН"})
        return {"ok": False, "status": "rejected_norm", "error": f"код {code} не в базе"}
    base_pos["norm_source_kind"] = str(norm.get("_source_kind") or "seed_yaml")
    base_pos["norm_source_path"] = str(norm.get("_source_path") or "config/domain/gesn_seed.yaml")
    if base_pos["norm_source_kind"] == "structured_sqlite":
        from proxy.smeta_core.integrity import normative_base_integrity

        base_pos["norm_source_integrity"] = normative_base_integrity(
            base_path=base_pos["norm_source_path"]
        )
    norm_profile = _norm_profile_for_code(code, norm)
    norm_card = norm_profile.get("model_card") if isinstance(norm_profile.get("model_card"), dict) else {}
    norm_questions = _unresolved_norm_questions(
        norm_profile,
        user_slots=user_slots,
        question_text=str(state.get("question_text") or ""),
    )
    if norm_profile:
        base_pos["norm_conditions"] = [str(x) for x in (norm_profile.get("condition_hints") or [])[:8]]
        base_pos["norm_card"] = {
            "measure": str(norm_card.get("measure") or "")[:160],
            "conditions_to_check": [str(x)[:80] for x in (norm_card.get("conditions_to_check") or [])[:8]],
            "warnings": [str(x)[:120] for x in (norm_card.get("warnings") or [])[:3]],
        }
    if norm_questions:
        if state.get("assumption_mode"):
            base_pos["assumptions"] = list(base_pos.get("assumptions", [])) + [
                "условия применимости нормы приняты по сценарию: " + ", ".join(norm_questions[:6])
            ]
        else:
            base_pos["norm_questions"] = norm_questions
    factor, base_unit = _norm_unit_factor(norm.get("unit", ""))
    # Gate 4: объём из FORMULA CATALOG по element_type + СЛОТЫ (формула НЕ от модели и НЕ
    # придумывает входы). Нет критичного слота (глубина/толщина/геометрия стен) → needs_input.
    if et in FORMULA_CATALOG:
        spec, ns, missing, slot_assumptions = resolve_slots(
            et,
            state["geom"],
            user_slots,
            allow_defaults=_env_bool("LES_SMETA_FORMULA_DEFAULTS_ENABLED", True),
        )
        direct_slot = _DIRECT_QTY_SLOT_BY_UNIT.get(_canon_unit((spec or {}).get("unit", "")))
        if direct_slot and direct_slot in user_slots and _is_number(user_slots.get(direct_slot)):
            phys = _f(user_slots.get(direct_slot))
            base_pos["physical_unit"] = _canon_unit(spec["unit"])
            base_pos["formula"] = direct_slot
            source = _quantity_candidate_by_slot(state.get("quantity_candidates", [])).get(direct_slot)
            if source:
                base_pos["quantity_source"] = source
            base_pos["assumptions"] = list(base_pos.get("assumptions", [])) + [
                f"{direct_slot}={round(phys, 6)} (прямой объём из запроса)"
            ]
        elif missing:
            visible_missing = [
                "area_total_m2" if str(slot) in {"S", "S1"} else str(slot)
                for slot in missing
            ]
            state["positions"].append({**base_pos, "status": "needs_input",
                                       "missing_slots": visible_missing,
                                       "reason": f"нет параметров: {', '.join(visible_missing)}"})
            return {"ok": True, "status": "needs_input", "missing_slots": visible_missing,
                    "reason": f"для расчёта нужны: {', '.join(visible_missing)} — спроси пользователя"}
        else:
            try:
                phys = _eval_formula(spec["expr"], ns)
            except Exception as e:  # noqa: BLE001
                state["positions"].append({**base_pos, "status": "needs_input", "reason": str(e)[:80]})
                return {"ok": True, "status": "needs_input", "reason": str(e)[:80]}
            base_pos["physical_unit"] = _canon_unit(spec["unit"])      # единица из каталога, не от модели
            base_pos["assumptions"] = list(base_pos.get("assumptions", [])) + slot_assumptions
            base_pos["formula"] = spec["expr"]
    else:
        # Legacy escape hatch: arbitrary model formulas are disabled by default. The model should
        # pass numeric slots; code evaluates only known calculator formulas or direct quantities.
        qty_formula = str(args.get("qty_formula", "")).strip()
        direct_slot = (
            _DIRECT_QTY_SLOT_BY_UNIT.get(_canon_unit(base_pos.get("physical_unit", "")))
            or _DIRECT_QTY_SLOT_BY_UNIT.get(_canon_unit(base_unit))
        )
        if direct_slot and direct_slot in user_slots and _is_number(user_slots.get(direct_slot)):
            phys = _f(user_slots.get(direct_slot))
            base_pos["physical_unit"] = _canon_unit(base_pos.get("physical_unit") or base_unit)
            base_pos["formula"] = direct_slot
            base_pos["assumptions"] = list(base_pos.get("assumptions", [])) + [
                f"{direct_slot}={round(phys, 6)} (прямой объём из ВОР/ТЗ)"
            ]
        elif qty_formula and _env_bool("LES_SMETA_LEGACY_QTY_FORMULA_ENABLED", True):
            try:
                phys = _eval_formula(qty_formula, state["geom"])
            except Exception as e:  # noqa: BLE001
                state["positions"].append({**base_pos, "status": "needs_input", "reason": str(e)[:80]})
                return {"ok": True, "status": "needs_input", "reason": str(e)[:80]}
        elif et == "engineering_networks":
            reason = (
                "для инженерных сетей нужно уточнить раздел (ВК/ОВ/ЭОМ/СС), "
                "протяжённость трасс, точки подключения и оборудование"
            )
            state["positions"].append({**base_pos, "status": "needs_input", "reason": reason})
            return {"ok": True, "status": "needs_input", "reason": reason}
        else:
            if et:
                reason = (
                    f"нет расчётной формулы для element_type={et}; нужен прямой объём, площадь, "
                    "длина, масса или количество именно для этой работы"
                )
            else:
                reason = (
                    "нужен прямой объём, площадь, длина, масса или количество именно для этой работы"
                )
            state["positions"].append({**base_pos, "status": "needs_input", "reason": reason})
            return {"ok": True, "status": "needs_input", "reason": reason}
    # единицы: физическая ↔ базовая единица нормы
    unit_factor = _unit_conversion_factor(base_pos["physical_unit"], base_unit)
    if unit_factor is None:
        reason = f"единица несовместима: измеритель исходного объёма ({base_pos['physical_unit']}) не подходит к измерителю нормы ({base_unit})"
        state["positions"].append({**base_pos, "status": "needs_input", "phys_qty": phys,
                                   "reason": reason})
        return {"ok": True, "status": "needs_input",
                "reason": reason}
    # Direct quantity guard: when the user gave one physical quantity (mass/volume/area),
    # the planner may split a single requested work into optional sub-works and reuse the same
    # code+quantity. That would multiply money without evidence. Keep the first computed
    # position; require a separate quantity/share for the rest.
    direct_slots = set(_DIRECT_QTY_SLOT_BY_UNIT.values())
    is_direct_quantity = base_pos.get("formula") in direct_slots
    # Magnitude guard is for formula-derived geometry. A direct quantity from the user is already
    # the physical quantity being priced; comparing it to planner placeholder geometry rejects
    # valid inputs such as "trench excavation, volume 200 m3".
    if not is_direct_quantity:
        mag_ok, bound, mag_reason = _magnitude_check(base_pos["physical_unit"], phys, state["geom"])
        if not mag_ok:
            state["positions"].append({**base_pos, "status": "rejected_magnitude", "phys_qty": phys,
                                       "bound": bound, "reason": mag_reason})
            return {"ok": True, "status": "rejected_magnitude", "phys_qty": phys, "upper_bound": bound,
                    "reason": mag_reason + " — проверь формулу"}
    if is_direct_quantity:
        for prev in state.get("positions", []):
            prev_operation = str(prev.get("operation_key") or _direct_operation_key(str(prev.get("work") or "")))
            same_operation = (
                not operation_key
                or not prev_operation
                or operation_key == prev_operation
                or _is_optional_direct_work(str(base_pos.get("work") or ""))
            )
            if (
                prev.get("status") == "computed"
                and prev.get("code") == code
                and _canon_unit(prev.get("physical_unit", "")) == _canon_unit(base_pos["physical_unit"])
                and str(prev.get("formula") or "") == str(base_pos.get("formula") or "")
                and abs(_f(prev.get("phys_qty")) - _f(phys)) < 1e-9
                and same_operation
            ):
                reason = (
                    "дублирует уже посчитанную позицию с тем же кодом и физическим объёмом; "
                    "нужна отдельная операция, доля или отдельный объём"
                )
                state["positions"].append({
                    **base_pos,
                    "status": "skipped_duplicate",
                    "phys_qty": phys,
                    "norm_unit": norm.get("unit", ""),
                    "reason": reason,
                    "duplicate_of": prev.get("work") or prev.get("code"),
                })
                return {"ok": True, "status": "skipped_duplicate", "phys_qty": phys, "reason": reason}
    # перевод в измеритель нормы (КОД, не модель)
    phys_in_norm_unit = phys * unit_factor
    qty_for_estimate = round(phys_in_norm_unit / factor, 6) if factor else phys_in_norm_unit
    state["positions"].append({**base_pos, "status": "computed", "phys_qty": phys,
                               "qty": qty_for_estimate, "norm_unit": norm.get("unit", ""),
                               "conversion": f"{phys} {base_pos['physical_unit']} × {unit_factor} / {factor}"})
    return {"ok": True, "status": "computed", "phys_qty": phys, "norm_unit": norm.get("unit", ""),
            "quantity_for_estimate": qty_for_estimate, "positions_so_far": len(state["positions"])}


def _exec_tool(name: str, args: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "propose_schema":
            missing_required = [k for k in _REQUIRED_SCHEMA if not args.get(k)]
            area = _f(state.get("object_area_m2"))
            model_area = _f(args.get("area_total_m2"))
            state["schema"] = dict(args)
            assumptions = [str(x) for x in (args.get("assumptions") or []) if str(x).strip()]
            state["scenario_assumptions"] = assumptions
            if state.get("object_area_m2"):
                state["schema"]["area_total_m2"] = state["object_area_m2"]
            elif state.get("assumption_mode") and model_area:
                area = model_area
                state["schema"]["area_total_m2"] = model_area
                if not assumptions:
                    assumptions = [f"площадь объекта {model_area:g} м2 принята по допущению пользователя"]
                    state["scenario_assumptions"] = assumptions
            elif model_area:
                state["schema"]["area_total_m2"] = None
            area_is_evidence = bool(state.get("object_area_m2")) or bool(state.get("assumption_mode") and model_area)
            if not missing_required and area and area_is_evidence:
                levels = int(_f(args.get("levels_below_ground")) or _f(args.get("floors")) or 1) or 1
                state["geom"] = _geometry(area, levels, {"geometry": {"H": 3.0}})
                return {"ok": True, "geometry": {k: round(v, 3) for k, v in state["geom"].items()},
                        "missing_inputs": list(args.get("missing_inputs", []) or [])}
            missing_inputs = list(args.get("missing_inputs", []) or [])
            if not state.get("object_area_m2") and model_area and not state.get("assumption_mode"):
                missing_inputs.append("area_total_m2 не подтверждена текстом запроса")
            if _env_bool("LES_SMETA_CODE_GEOMETRY_ENABLED", False) and not area:
                missing_inputs.append("area_total_m2")
            return {"ok": not missing_required, "missing_required": missing_required, "missing_inputs": missing_inputs}
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
    assumptions = value[7] if len(value) >= 8 and isinstance(value[7], list) else []
    return {
        "work": value[0],
        "work_description": value[1],
        "work_family": value[2],
        "element_type": value[3],
        "action": value[4],
        "unit_hint": value[5],
        "slots": slots,
        "assumptions": assumptions,
    }


def _work_items_from_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    raw = plan.get("works") if "works" in plan else plan.get("work_items")
    items: list[dict[str, Any]] = []
    for value in raw if isinstance(raw, list) else []:
        item = _coerce_work_item(value)
        if item:
            items.append(item)
    return items


def _plan_missing_requirements(plan: dict[str, Any]) -> list[str]:
    schema = _schema_from_plan(plan)
    missing = [f"object.{k}" for k in _REQUIRED_SCHEMA if not schema.get(k)]
    if not _work_items_from_plan(plan):
        missing.append("works")
    return missing


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
                    state: dict[str, Any], *, max_steps: int = 16,
                    system_prompt: str | None = None) -> dict[str, Any]:
    assumption_note = (
        "Пользователь явно разрешил сценарную прикидку по допущениям. Отрази принятые исходные "
        "в object.assumptions или work assumptions; не выдавай их за проектные факты."
        if state.get("assumption_mode") else ""
    )
    raw_slots_note = (
        f"Извлечённые из текста параметры-кандидаты: {state.get('raw_user_slots')}."
        if state.get("raw_user_slots") else
        "Если параметров нет, оставь missing_inputs/пустые slots; код не будет выдумывать."
    )
    calc_slots_note = (
        f"Калькулятор уже может использовать без привязки модели только: {state.get('user_slots')}."
        if state.get("user_slots") else
        "Параметры-кандидаты не являются глобальными inputs калькулятора: привяжи нужные числа в slots конкретных работ."
    )
    quantity_note = _quantity_candidates_prompt_note(state.get("quantity_candidates", []))
    messages = [
        {"role": "system", "content": system_prompt or BATCH_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Объект/контекст:\n{question}\n\n{raw_slots_note}\n{calc_slots_note}\n{quantity_note}\n{assumption_note}"
        ).strip()},
    ]
    state["steps"] = 1
    raw = complete(messages) or ""
    plan = _extract_json(raw)
    trace: list[dict[str, Any]] = []

    if plan is None:
        messages.extend([
            {"role": "assistant", "content": raw[:2000]},
            {"role": "user", "content": (
                "Предыдущий ответ не был машинным JSON. Верни тот же план повторно: "
                "ровно один JSON-объект формата {\"object\": {...}, \"works\": [...]}. "
                "Без markdown, без пояснений, без текста до или после JSON."
            )},
        ])
        retry_raw = complete(messages) or ""
        plan = _extract_json(retry_raw)
        trace.append({"tool": "planner_repair", "status": "ok" if plan is not None else "err"})

    if plan is None:
        res = _finalize(state, note="модель не вернула машинный JSON-план")
        res["trace"] = trace
        res["planner_status"] = "no_json"
        return res

    if plan.get("tool") or plan.get("final"):
        messages.extend([
            {"role": "assistant", "content": raw[:2000]},
            {"role": "user", "content": (
                "Это старый tool-call формат. В сметном режиме сейчас один контракт: "
                "верни тот же смысл как smeta_work_plan_v1, ровно один JSON-объект "
                "{\"object\": {...}, \"works\": [...]}. Не вызывай tool/final, не пиши коды норм, "
                "markdown или пояснения."
            )},
        ])
        retry_raw = complete(messages) or ""
        retry_plan = _extract_json(retry_raw)
        if retry_plan is not None and not (retry_plan.get("tool") or retry_plan.get("final")):
            plan = retry_plan
            trace.append({"tool": "planner_legacy_repair", "status": "ok"})
        else:
            res = _finalize(state, note="модель вернула старый tool-call вместо smeta_work_plan_v1")
            res["trace"] = trace + [{"tool": "planner_legacy_repair", "status": "err"}]
            res["planner_status"] = "legacy_tool_call"
            return res

    missing_plan = _plan_missing_requirements(plan)
    if missing_plan:
        messages.extend([
            {"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)[:2500]},
            {"role": "user", "content": (
                "JSON получен, но он неполный для инструментов: не хватает "
                f"{', '.join(missing_plan)}. Верни исправленный полный JSON для того же объекта: "
                "{\"object\":{\"object_type\":\"...\",\"area_total_m2\":150|null,\"floors\":1,"
                "\"levels_below_ground\":0,\"structural_system\":\"...\",\"missing_inputs\":[]},"
                "\"works\":[[\"work\",\"search description\",\"family\",\"element\",\"action\",\"unit\",{}]]}. "
                "Если площадь/габариты не даны в запросе, area_total_m2=null и missing_inputs включает "
                "площадь/габариты. Если пользователь разрешил допущения, используй правила role-pack "
                "для сценарного work-plan и заполни assumptions. Без markdown и пояснений."
            )},
        ])
        retry_raw = complete(messages) or ""
        retry_plan = _extract_json(retry_raw)
        if retry_plan is not None and not _plan_missing_requirements(retry_plan):
            plan = retry_plan
            trace.append({"tool": "planner_schema_repair", "status": "ok", "missing": missing_plan})
        else:
            trace.append({"tool": "planner_schema_repair", "status": "err", "missing": missing_plan})

    schema = _schema_from_plan(plan)
    obs_schema = _exec_tool("propose_schema", schema, state)
    trace.append({"tool": "propose_schema",
                  "status": "ok" if obs_schema.get("ok") else "err",
                  "missing_inputs": obs_schema.get("missing_inputs")
                  or obs_schema.get("missing_required") or []})

    work_entries: list[dict[str, Any]] = []
    for raw_item in _work_items_from_plan(plan):
        item, corrections = _normalize_work_item(raw_item)
        intent_hints = _work_item_intent_hints(item)
        work_description = str(item.get("work_description") or item.get("work") or "")
        if (
            _env_bool("LES_SMETA_SEARCH_QUERY_ENRICHMENT_ENABLED", False)
            and
            item.get("element_type") == "metal_assembly"
            and state.get("user_slots", {}).get("mass_t")
            and "масс" not in work_description.lower()
        ):
            work_description = f"{work_description} масса {state['user_slots']['mass_t']} т"
        search_args = {
            "work_description": work_description,
            "work_family": str(item.get("work_family") or ""),
            "element_type": str(item.get("element_type") or ""),
            "action": str(item.get("action") or ""),
            "unit_hint": str(item.get("unit_hint") or ""),
        }
        search = _exec_tool("search_norm", search_args, state)
        candidates = _as_items(search.get("candidates"))
        work_entries.append({
            "item": item,
            "search": search,
            "candidates": candidates,
            "corrections": corrections,
            "intent_hints": intent_hints,
        })
        trace.append({
            "tool": "search_norm",
            "status": search.get("status") or ("ok" if search.get("ok") else "err"),
            "work": item.get("work") or item.get("work_description") or "",
            "candidates": _candidate_codes(candidates),
            "selection": search.get("selection", {}),
            "normalized": corrections,
            "intent_hints": intent_hints,
        })

    batch_choices = _model_select_candidates_batch(
        entries=work_entries,
        messages=messages,
        complete=complete,
    )
    if batch_choices:
        state["steps"] = int(state.get("steps") or 0) + 1

    for entry_index, entry in enumerate(work_entries):
        item = entry["item"]
        search = entry["search"]
        candidates = entry["candidates"]
        if entry_index in batch_choices:
            bind_candidate, bind_index, choice_trace = batch_choices[entry_index]
        else:
            bind_candidate, bind_index, choice_trace = _model_select_candidate(
                item=item,
                search=search,
                candidates=candidates,
                messages=messages,
                complete=complete,
            )
        if choice_trace:
            if not choice_trace.get("batch"):
                state["steps"] = int(state.get("steps") or 0) + 1
            trace.append(choice_trace)
        if bind_candidate:
            choice_status = str((choice_trace or {}).get("status") or "")
            model_selected_norm = choice_status == "selected"
            if not model_selected_norm:
                _append_unbound_position(item, search, state)
                trace.append({
                    "tool": "add_position",
                    "status": "skipped_nonmodel_norm_bind",
                    "work": item.get("work") or item.get("work_description") or "",
                    "code": bind_candidate.get("norm_code", ""),
                    "reason": "норма не была явно выбрана моделью; автоматическая привязка выключена",
                })
                continue
            selection = search.get("selection") if isinstance(search.get("selection"), dict) else {}
            norm_assumptions = []
            if model_selected_norm:
                reason = str(choice_trace.get("reason") or "").strip()
                norm_assumptions.append(
                    "норма выбрана моделью из shortlist search_norm"
                    + (f": {reason}" if reason else "")
                )
            elif search.get("status") != "found":
                norm_assumptions.append(
                    "норма взята из включённого режима автоматической привязки; требуется проверка сметчиком"
                )
            if bind_index > 0:
                norm_assumptions.append(
                    "выбран не первый вариант из найденных норм; требуется проверка сметчиком"
                )
            add_args = {
                "work": item.get("work") or item.get("work_description") or bind_candidate.get("title") or "",
                "code": bind_candidate.get("norm_code", ""),
                "work_family": item.get("work_family") or search.get("work_family") or "",
                "element_type": item.get("element_type") or search.get("element_type") or "",
                "slots": item.get("slots") if isinstance(item.get("slots"), dict) else {},
                "assumptions": norm_assumptions + [
                    str(a) for a in (item.get("assumptions") or []) if str(a).strip()
                ],
                "selection_kind": str((choice_trace or {}).get("selection_kind") or ""),
                "is_analog": bool((choice_trace or {}).get("is_analog")),
                "analog_limitations": list((choice_trace or {}).get("analog_limitations") or []),
                "selection_reason": str((choice_trace or {}).get("reason") or ""),
            }
            obs = _exec_tool("add_position", add_args, state)
            trace.append({"tool": "add_position",
                          "status": obs.get("status") or ("ok" if obs.get("ok") else "err"),
                          "work": add_args["work"],
                          "code": add_args["code"],
                          "selection": selection,
                          "candidate_index": bind_index})
        else:
            _append_unbound_position(item, search, state)

    res = _finalize(state)
    res["trace"] = trace
    res["planner_status"] = "batch"
    return res


_CRITICAL = {"ambiguous"}


def _is_critical_status(status: Any) -> bool:
    st = str(status or "")
    return st in _CRITICAL or st.startswith("rejected_")


def _finalize(state: dict[str, Any], *, note: str = "") -> dict[str, Any]:
    """Finalize model-selected rows through the single smeta_core policy."""
    from proxy.smeta_core.calculator import calculate_scenario
    from proxy.smeta_core.contracts import CalculationStatus, NormBinding, WorkItem
    from proxy.smeta_core.lsr_renderer import complete_lsr_trace

    buckets: dict[str, list] = {
        "computed": [], "needs_input": [], "rejected": [], "by_assumption": [], "skipped": [],
    }
    work_items: list[WorkItem] = []
    bindings: list[NormBinding] = []
    for index, position in enumerate(state.get("positions", []), 1):
        status = str(position.get("status") or "")
        if status == "skipped_duplicate":
            buckets["skipped"].append(position)
            continue
        work_id = str(position.get("work_id") or f"harness-{index}")
        work = WorkItem(
            work_id=work_id,
            title=str(position.get("work") or "Позиция сметы"),
            quantity=_f(position.get("phys_qty")) if position.get("phys_qty") not in (None, "") else None,
            unit=str(position.get("physical_unit") or ""),
            section=str(position.get("section") or "Без раздела"),
            source_row=index,
            source_refs=("model_work_plan",),
            assumptions=tuple(str(item) for item in (position.get("assumptions") or []) if str(item)),
        )
        work_items.append(work)
        if _is_critical_status(status):
            buckets["rejected"].append(position)
            continue
        if status == "needs_input":
            buckets["needs_input"].append(position)
            continue
        if status == "computed":
            buckets["computed"].append(position)
            if position.get("assumptions"):
                buckets["by_assumption"].append(position)
            bindings.append(NormBinding(
                work_id=work_id,
                norm_code=str(position.get("code") or ""),
                selected_by="model",
                selection_kind=str(position.get("selection_kind") or ""),
                is_analog=bool(position.get("is_analog")),
                reason=str(position.get("selection_reason") or "явный выбор модели из search_norm candidates"),
                source_refs=("model_norm_choice",),
                analog_limitations=tuple(
                    str(item) for item in (position.get("analog_limitations") or []) if str(item).strip()
                ),
            ))

    scenario = calculate_scenario(
        work_items,
        bindings,
        title="Локальный сметный расчет (смета)",
        book=state.get("pricebook") or None,
    )
    trace = complete_lsr_trace(scenario)
    summary = trace.get("summary") or {}
    flags = list(summary.get("flags") or [])
    price_requirements = [
        {"message": flag}
        for flag in flags
        if any(marker in str(flag) for marker in ("нужен КАЦ", "нужна ставка", "нужна цена"))
    ]
    smr = round(float(summary.get("total_without_vat") or summary.get("total") or 0.0), 2)
    vat = round(float(summary.get("vat") or 0.0), 2)
    complete = scenario.calculation_status == CalculationStatus.COMPLETE
    final = {
        "smr": smr,
        "contingency": 0.0,
        "vat": vat,
        "vat_pct": summary.get("vat_pct"),
        "grand_total": round(float(summary.get("total_with_vat") or smr), 2),
        "positions": int(summary.get("bound_rows") or 0),
        "known_cost_only": bool(price_requirements),
        "unpriced_resource_count": len(price_requirements),
        "note": "Непредвиденные затраты не начислены; НДС применяется по period-aware tax policy.",
    }
    partial = {
        **final,
        "money_visible": True,
        "reason": "неполный состав работ, нормы, параметры, НР/СП или цены",
    }
    blockers = [
        {"position": item.get("work", ""), "reason": item.get("status"), "candidate": item.get("code"), "detail": item.get("reason", "")}
        for item in buckets["rejected"]
    ]
    blockers.extend(scenario.blockers)
    return {
        "ok": bool(buckets["computed"]),
        "preliminary": not complete,
        "total_status": "complete" if complete else ("partial" if buckets["computed"] else "blocked"),
        "partial_total": None if complete or not buckets["computed"] else partial,
        "final_total": final if complete else None,
        "blockers": blockers,
        "schema": state.get("schema", {}),
        "computed": buckets["computed"],
        "needs_input": buckets["needs_input"],
        "rejected": buckets["rejected"],
        "norm_checks": [item for item in buckets["computed"] if item.get("norm_questions")],
        "price_requirements": price_requirements,
        "pricing_status": "partial" if flags else "complete",
        "skipped": buckets["skipped"],
        "by_assumption": buckets["by_assumption"],
        "assumption_mode": bool(state.get("assumption_mode")),
        "scenario_assumptions": list(state.get("scenario_assumptions") or []),
        "estimate": trace,
        "steps": state.get("steps", 0),
        "note": note,
        "source": "smeta_core",
        "evidence_status": scenario.evidence_status.value,
        "calculation_status": scenario.calculation_status.value,
    }
def run_estimate_harness(question: str, complete: Callable[[list[dict[str, str]]], str],
                         *, max_steps: int = 16) -> dict[str, Any]:
    # Gate 4: параметры из запроса → слоты (уточнение в одном запросе:
    # «… глубина 6м плита 400мм»).
    raw_user_slots = parse_params(question)
    object_area_m2 = _object_area_from_text(question, raw_user_slots)
    assumption_mode = _assumptions_authorized(question)
    explicit_direct_work = is_explicit_work_estimate_request(question)
    quantity_candidates = _quantity_candidates_from_slots(raw_user_slots, question)
    user_slots = _calculator_slots_from_user_slots(
        raw_user_slots,
        explicit_direct_work=explicit_direct_work,
    )
    smeta_sources = _smeta_service_source_status()
    pricebook = parse_pricebook_hint(question)
    state: dict[str, Any] = {"schema": {}, "geom": {}, "positions": [], "steps": 0,
                             "object_area_m2": object_area_m2,
                             "question_text": question,
                             "raw_user_slots": raw_user_slots,
                             "user_slots": user_slots, "pricebook": pricebook,
                             "quantity_candidates": quantity_candidates,
                             "smeta_service_sources": smeta_sources,
                             "assumption_mode": assumption_mode,
                             "scenario_assumptions": []}
    notebook_excerpt = gesn_notebook_prompt_excerpt()
    system_prompt = build_smeta_batch_system_prompt(BATCH_TOOL_CONTRACT, notebook_context=notebook_excerpt)
    result = _run_batch_plan(question, complete, state, max_steps=max_steps, system_prompt=system_prompt)
    direct_slots = sorted(set(user_slots) & _DIRECT_QTY_SLOTS)
    result["direct_quantity_estimate"] = bool(explicit_direct_work and direct_slots)
    result["direct_quantity_slots"] = direct_slots
    result["quantity_candidates"] = quantity_candidates
    result["smeta_service_sources"] = smeta_sources
    result["notebook_context"] = {
        "schema": "notebook_context_v1",
        "role": "navigation",
        "is_evidence": False,
        "service_notebooks": ["gesn"],
        "excerpt": notebook_excerpt,
    }
    from proxy.smeta_core.workflow import finalize_estimate_result

    return finalize_estimate_result(result, source_status=smeta_sources)


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[m.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None
