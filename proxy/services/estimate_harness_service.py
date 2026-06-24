"""Сметный ХАРНЕСС (экспериментальный профиль smeta_harness) — петля инструментов.

Цель (Олег): доказать ПЕРЕХОД ОТ ДИСПЕТЧЕРА К ХАРНЕССУ на объекте ВНЕ YAML (паркинг):
модель получает объект → раскладывает в типизированную схему → код валидирует → модель
строит ВОР → инструменты возвращают нормы-кандидаты/объёмы/числа → модель собирает ответ,
НЕ генерируя числа из головы. НЕ трогает старый smeta/ProfileResolver/router/RAG — сидит рядом.

Жёсткие правила первого среза:
  • search_norm — ТОНКИЙ кандидатор (лексика по базе ГЭСН), статус found/ambiguous/not_found.
    Не «магический выбор нормы» — возвращает кандидатов, выбор за моделью/валидатором.
  • НЕ хватает входа для формулы → НЕ считаем молча: позиция помечается needs_input.
  • Результат может быть ПРЕДВАРИТЕЛЬНЫМ (часть посчитана, часть — кандидаты, часть — нет данных).
    Это честнее фальшивого красивого ЛСР.
  • Ни одно число в финале не из текста модели — только из calc/get_norm/формул.

Протокол провайдер-агностичный: модель отвечает РОВНО одним JSON. complete(messages)->str
инъектируется (тест — скрипт; прод — облако/MLX: декомпозиция = где большая модель уместна).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, Callable

from proxy.services.object_estimate_service import _eval_formula, _f, _geometry

# ── search_norm: тонкий кандидатор поверх существующей базы ГЭСН (0 LLM) ──────────────────

@lru_cache(maxsize=1)
def _norm_index() -> list[tuple[str, str, str]]:
    from proxy.services.gesn_service import load_base_norms
    return [(code, str(n.get("name", "")).lower(), str(n.get("unit", "")))
            for code, n in (load_base_norms() or {}).items()]


def search_norm(work_description: str, *, unit_hint: str = "", top_k: int = 5) -> dict[str, Any]:
    """Описание работы → КАНДИДАТЫ кодов ГЭСН (лексика по названию нормы). Не выбирает за модель.
    status: found (уверенный лидер) | ambiguous (близкие/слабые) | not_found."""
    words = [w for w in re.findall(r"[а-яёa-z0-9]{3,}", (work_description or "").lower())]
    if not words:
        return {"status": "not_found", "candidates": [], "missing_inputs": ["work_description"]}
    uh = (unit_hint or "").lower().strip()
    scored: list[tuple[float, str, str, str]] = []
    for code, name, unit in _norm_index():
        score = sum(1 for w in words if w in name)
        if not score:
            continue
        if uh and uh in unit.lower():       # лёгкий буст по единице измерения
            score += 0.5
        scored.append((score, code, name, unit))
    if not scored:
        return {"status": "not_found", "candidates": [], "hint": "переформулируй work_description"}
    scored.sort(key=lambda t: (-t[0], t[1]))
    top = scored[:top_k]
    cands = [{"norm_code": c, "title": nm, "unit": u, "score": round(s, 2)} for s, c, nm, u in top]
    # уверенность: лидер заметно сильнее второго → found, иначе ambiguous
    status = "found" if (len(top) == 1 or top[0][0] >= top[1][0] + 1.5) else "ambiguous"
    return {"status": status, "candidates": cands}


# ── схема объекта: модель предлагает, КОД валидирует ─────────────────────────────────────

_REQUIRED_SCHEMA = ("object_type", "area_total_m2")


def _validate_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Проверка типизированной схемы объекта + вывод геометрии. Числа не выдумываем."""
    missing_required = [k for k in _REQUIRED_SCHEMA if not schema.get(k)]
    area = _f(schema.get("area_total_m2"))
    levels = int(_f(schema.get("levels_below_ground")) or _f(schema.get("floors")) or 1) or 1
    geom = _geometry(area, levels, {"geometry": {"H": 3.0}}) if area else {}
    return {
        "ok": not missing_required and bool(area),
        "missing_required": missing_required,
        "missing_inputs": list(schema.get("missing_inputs", []) or []),
        "geometry": {k: round(v, 3) for k, v in geom.items()},
    }


# ── петля ───────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "Ты — инженер-сметчик. Разложи строительный ОБЪЕКТ в смету через ИНСТРУМЕНТЫ. Числа сам НЕ "
    "пиши — только инструменты. Отвечай РОВНО одним JSON и ничем больше.\n\n"
    "Шаги:\n"
    "1) {\"tool\":\"propose_schema\",\"args\":{\"object_type\":..,\"area_total_m2\":..,"
    "\"levels_below_ground\":..,\"structural_system\":..,\"included_sections\":[..],"
    "\"excluded_sections\":[..],\"missing_inputs\":[..]}} — ПЕРВЫМ. Код вернёт геометрию {S,N,S1,P,H}.\n"
    "2) {\"tool\":\"search_norm\",\"args\":{\"work_description\":\"..\",\"unit_hint\":\"м3|м2\"}} — "
    "кандидаты кодов ГЭСН на работу.\n"
    "3) {\"tool\":\"add_position\",\"args\":{\"work\":\"..\",\"code\":\"NN-NN-NNN-NN\",\"unit\":\"..\","
    "\"qty_formula\":\"<над S,N,S1,P,H>\",\"assumptions\":[..]}} — добавить позицию. Норму ГЭСН дают "
    "на «100 м3»/«10 м2» → дели формулу на 100/10. Нет нужного параметра в формуле — позиция "
    "пометится needs_input (это НОРМАЛЬНО, не выдумывай).\n"
    "4) {\"final\":true} — собрать. Результат может быть ПРЕДВАРИТЕЛЬНЫМ.\n\n"
    "Для подземного паркинга разделы: котлован/ограждение, гидроизоляция, фунд. плита, "
    "монолитный каркас, перекрытия, рампы. Один JSON за ход; коды — только из search_norm."
)


def _exec_tool(name: str, args: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "propose_schema":
            v = _validate_schema(args)
            state["schema"] = args
            state["geom"] = {}  # перезаполним из geometry
            from proxy.services.object_estimate_service import _geometry as _g
            if v["ok"]:
                state["geom"] = _g(_f(args.get("area_total_m2")),
                                   int(_f(args.get("levels_below_ground")) or _f(args.get("floors")) or 1) or 1,
                                   {"geometry": {"H": 3.0}})
            return v
        if name == "search_norm":
            return search_norm(str(args.get("work_description", "")), unit_hint=str(args.get("unit_hint", "")))
        if name == "add_position":
            from proxy.services.gesn_service import get_norm
            if not state.get("geom"):
                return {"ok": False, "error": "сначала propose_schema с площадью"}
            code = str(args.get("code", "")).strip()
            if get_norm(code) is None:
                return {"ok": False, "error": f"код {code} не в базе — возьми из search_norm"}
            formula = str(args.get("qty_formula", ""))
            try:
                qty = _eval_formula(formula, state["geom"])
                status = "computed"
            except Exception as e:  # нет переменной/плохая формула → НЕ считаем молча
                qty, status = None, "needs_input"
                pos = {"work": args.get("work", ""), "code": code, "unit": args.get("unit", ""),
                       "qty": None, "status": "needs_input", "reason": str(e)[:80],
                       "assumptions": list(args.get("assumptions", []) or [])}
                state["positions"].append(pos)
                return {"ok": True, "status": "needs_input", "reason": str(e)[:80],
                        "note": "позиция учтена как «нет данных» — это нормально"}
            pos = {"work": args.get("work", ""), "code": code, "unit": args.get("unit", ""),
                   "qty": qty, "qty_formula": formula, "status": status,
                   "assumptions": list(args.get("assumptions", []) or [])}
            state["positions"].append(pos)
            return {"ok": True, "status": status, "computed_qty": qty, "positions_so_far": len(state["positions"])}
        return {"ok": False, "error": f"неизвестный инструмент {name!r}"}
    except Exception as e:  # noqa: BLE001 — инструмент не роняет петлю
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _finalize(state: dict[str, Any], *, note: str = "") -> dict[str, Any]:
    """Собрать ПРЕДВАРИТЕЛЬНЫЙ результат: посчитанное → ЛСР; needs_input/допущения — явно.
    Числа — из get_norm/формул. Это НЕ финальная смета."""
    from proxy.services.gesn_service import get_norm
    from proxy.services.lsr_assembly_service import assemble
    from proxy.services.nr_sp_service import resolve as resolve_nr_sp

    computed, needs_input, by_assumption, missing_codes = [], [], [], []
    asm_positions = []
    for p in state.get("positions", []):
        if p.get("status") == "needs_input":
            needs_input.append(p)
            continue
        norm = get_norm(p["code"])
        if norm is None:
            missing_codes.append(p["code"])
            continue
        if p.get("assumptions"):
            by_assumption.append(p)
        computed.append(p)
        rs = resolve_nr_sp(norm.get("name", ""))
        asm_positions.append({"code": p["code"], "name": p.get("work") or norm.get("name", ""),
                              "unit": p["unit"], "qty": p["qty"], "section": "Конструктив",
                              "nr_pct": rs["nr_pct"], "sp_pct": rs["sp_pct"]})
    lsr = assemble(asm_positions) if asm_positions else {"summary": {"total": 0.0}}
    smr = round(_f(lsr.get("summary", {}).get("total")), 2)
    cont = round(smr * 0.02, 2)
    vat = round((smr + cont) * 0.20, 2)
    return {
        "ok": bool(computed),
        "preliminary": True,
        "schema": state.get("schema", {}),
        "computed": computed,
        "needs_input": needs_input,
        "by_assumption": by_assumption,
        "missing_codes": missing_codes,
        "estimate": lsr,
        "totals": {"smr": smr, "contingency": cont, "vat": vat,
                   "grand_total": round(smr + cont + vat, 2), "positions": len(computed)},
        "steps": state.get("steps", 0),
        "note": note,
        "source": "harness",
    }


def run_estimate_harness(
    question: str,
    complete: Callable[[list[dict[str, str]]], str],
    *,
    max_steps: int = 14,
) -> dict[str, Any]:
    """Агентная петля: модель раскладывает объект → дёргает инструменты → собираем ПРЕДВАРИТЕЛЬНО."""
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
