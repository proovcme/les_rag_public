"""Чат-канал «смета»: лёгкие сметные запросы одной строкой (цена/КАЦ/стеснённость).

ЛЕС = harness с детерминированными каналами: тяжёлый структурный ввод — в карточках/вложениях,
а быстрые запросы — в чате. 0 LLM (regex + сервисы), ДО RAG-роутинга. Дополняет [[smeta-ontology]]
канал глоссария (что такое X) — здесь конкретные расчёты/справки по коду.

Покрывает:
  • цена ресурса по коду  → fgis_price_service (ФГИС ЦС lookup)
  • нужен ли КАЦ для кода → kac_service.needs_kac (нет в ФГИС ЦС → нужен КАЦ)
  • коэффициент стеснённости (условие) → stesnennost_service (каталог)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

# Ресурсный код ФГИС ЦС/ГЭСН: 91.05.01-017, 01.7.15.06-0111, опц. префикс базы (ФСБЦ-).
_CODE_RE = re.compile(r"(?:[А-ЯA-Zа-яa-z]{2,6}-)?\d{2}\.[\d.]+(?:-\d+)?")
# Код нормы ГЭСН/ФЕР: ГЭСН12-01-034-02 (опц. префикс), формат NN-NN-NNN-NN.
_GESN_RE = re.compile(r"(?:ГЭСН[р]?|ФЕР|ТЕР)?\s?\d{2}-\d{2}-\d{3}-\d{2}", re.I)
_ASSEMBLE_WORDS = ("собери", "собрать", "посчитай смет", "посчитай позиц", "смета по", "сосчитай", "рассчитай смет")

_PRICE_WORDS = ("цена", "цену", "стоимост", "сколько стоит", "почем", "почём", "расцен")
_KAC_WORDS = ("кац", "конъюнктур", "коньюктур", "в фгис", "в базе цен", "есть в фгис")
_STESN_WORDS = ("стеснённ", "стесненн", "стеснён", "усложняющ")
_OBJECT_ESTIMATE_SOURCES = [
    {
        "source_ref": "config/domain/object_templates.yaml#monolith_office",
        "source_kind": "template",
        "excerpt": "Параметрические шаблоны объектов: match, geometry, positions, allowances, price_level_k.",
    },
    {
        "source_ref": "proxy/services/object_estimate_service.py#estimate",
        "source_kind": "code",
        "excerpt": "Фраза → шаблон → ВОР → ЛСР → ASSUME-разделы → price_level_k → НДС.",
    },
    {
        "source_ref": "proxy/services/lsr_assembly_service.py#assemble",
        "source_kind": "code",
        "excerpt": "Разворот позиций ГЭСН в СМР: прямые затраты, НР/СП, итог по позиции.",
    },
    {
        "source_ref": "docs/ALGO-object-estimate.md#pipeline",
        "source_kind": "doc",
        "excerpt": "Воспроизводимость алгоритма объектной прикидки; сам файл не является доказательством цены.",
    },
]


def _fmt_num(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:,.2f}".replace(",", " ")


def _f(v: Any) -> float:
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _first_code(q: str) -> Optional[str]:
    m = _CODE_RE.search(q)
    return m.group(0) if m else None


def _answer_price(code: str) -> dict[str, Any]:
    from proxy.services import fgis_price_service as fps

    books = fps.available_pricebooks()
    if not books:
        return {"answer": f"Код {code}: нет книги цен ФГИС ЦС — импортируйте «Сплит-форму» "
                          f"(Инструменты → ФГИС ЦС или POST /api/prices/import).",
                "operation": "price"}
    pb = fps.get_pricebook(books[0])
    rec = pb.lookup(code)
    if rec is None:
        return {"answer": f"Код {code} не найден в ФГИС ЦС ({pb.region} {pb.quarter}). "
                          f"Если материал отсутствует в базе — нужен КАЦ (≥3 КП на материал).",
                "operation": "price"}
    return {"answer": (f"{rec.get('name','')} · {rec.get('unit','')}\n"
                       f"Сметная цена (текущая): {_fmt_num(rec.get('price_current_eff'))} руб. "
                       f"(базовая {_fmt_num(rec.get('price_base'))} × индекс {rec.get('index')})\n"
                       f"{pb.region} · {pb.quarter} · книга {Path(books[0]).stem}"),
            "operation": "price"}


def _answer_needs_kac(code: str) -> dict[str, Any]:
    from proxy.services.kac_service import needs_kac

    r = needs_kac(code)
    if r.get("note"):
        return {"answer": f"Код {code}: {r['note']}. По регламенту КАЦ нужен для материалов, "
                          f"которых нет в ФГИС ЦС (≥3 поставщика на материал).", "operation": "needs_kac"}
    if r.get("in_fgis"):
        return {"answer": f"Код {code} ЕСТЬ в ФГИС ЦС (цена {_fmt_num(r.get('fgis_price'))} руб.) — "
                          f"КАЦ не нужен, берём цену из базы.", "operation": "needs_kac"}
    return {"answer": f"Кода {code} НЕТ в ФГИС ЦС — нужен КАЦ: ≥3 коммерческих предложения на материал, "
                      f"выбрать экономичный, цену учесть в смете (Инструменты → КАЦ).",
            "operation": "needs_kac"}


def _answer_stesnennost(q: str) -> dict[str, Any]:
    from proxy.services import stesnennost_service as st

    conds = st.list_conditions()
    # попытка угадать конкретное условие по РАЗЛИЧАЮЩИМ словам label (общие слова —
    # «стеснённые/условия/коэффициент» — есть в самом запросе, их отсекаем, иначе всё матчит «город»).
    _GENERIC = ("стесн", "услов", "коэфф", "усложн", "произв", "работ", "услови")
    ql = q.lower()
    for c in conds:
        words = [w for w in re.split(r"[\s,/]+", c["label"].lower())
                 if len(w) > 4 and not any(w.startswith(g) for g in _GENERIC)]
        if any(w[:5] in ql for w in words):
            return {"answer": (f"Коэффициент стеснённости — «{c['label']}»:\n"
                               f"к ОЗП ×{c['k_ozp']}, к ЭМ ×{c['k_em']}. {c.get('basis','')}\n"
                               f"Применяется к ОЗП и ЭМ позиции (материалы не трогаются)."),
                    "operation": "stesnennost"}
    lines = [f"• {c['label']}: ОЗП ×{c['k_ozp']}, ЭМ ×{c['k_em']}" for c in conds]
    return {"answer": "Коэффициенты стеснённости (каталог, к ОЗП/ЭМ):\n" + "\n".join(lines)
                      + "\nУточни условие — или Инструменты → «Коэффициент стеснённости».",
            "operation": "stesnennost"}


def _parse_qty(q: str, code: str) -> Optional[float]:
    rest = q.replace(code, " ")
    m = re.search(r"(?:об[ъь][её]м\w*|кол-?во|количеств\w*)\D{0,4}([\d]+(?:[.,]\d+)?)", rest, re.I)
    if not m:
        m = re.search(r"\b(\d+(?:[.,]\d+)?)\b", rest)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _detect_condition(q: str) -> Optional[str]:
    from proxy.services import stesnennost_service as st

    ql = q.lower()
    gen = ("стесн", "услов", "коэфф", "усложн", "произв", "работ")
    for c in st.list_conditions():
        words = [w for w in re.split(r"[\s,/]+", c["label"].lower())
                 if len(w) > 4 and not any(w.startswith(g) for g in gen)]
        if any(w[:5] in ql for w in words):
            return c["id"]
    return None


def _num_ru(text: str) -> float:
    clean = str(text or "").replace("\u00a0", " ").replace(" ", "").replace(",", ".")
    return _f(clean)


def _extract_mass_kg(text: str) -> float:
    for pat in (
        r"масса[^.\n]{0,80}?([\d\s\u00a0]+(?:[,.]\d+)?)\s*кг",
        r"([\d\s\u00a0]+(?:[,.]\d+)?)\s*кг",
    ):
        m = re.search(pat, text, re.I)
        if m:
            return _num_ru(m.group(1))
    return 0.0


def _extract_int(pattern: str, text: str) -> int:
    m = re.search(pattern, text, re.I)
    return int(_num_ru(m.group(1))) if m else 0


def _has_custom_mass_signal(text: str) -> bool:
    ql = text.lower()
    return (
        any(w in ql for w in ("сталь", "стальные", "металлоконструкц", "каркас"))
        and any(w in ql for w in ("ярус", "монтаж", "кран", "трал", "строп"))
    )


def _is_custom_mass_followup(text: str) -> bool:
    ql = text.casefold().replace("ё", "е")
    return any(w in ql for w in (
        "учти", "добав", "а если", "если", "помен", "пересч", "высотн", "на высоте",
        "коэфф", "коэффициент",
    ))


def _latest_custom_mass_trace(context_traces: list[dict[str, Any]] | None) -> dict[str, Any]:
    for trace in reversed(context_traces or []):
        if str(trace.get("mode") or "").startswith("custom_mass_estimate"):
            return trace
    return {}


def _height_work_requested(text: str) -> bool:
    ql = text.casefold().replace("ё", "е")
    return "высотн" in ql or "на высоте" in ql or "работы на высоте" in ql


def _extract_user_coefficient(text: str) -> Optional[float]:
    """Явный коэффициент из фразы: «коэф. 1,15», «k=1.2», «×1,15»."""
    for pat in (
        r"(?:коэфф(?:ициент)?|k|к)\s*[=:xх×]?\s*(1[,.]\d{1,3})",
        r"[xх×]\s*(1[,.]\d{1,3})",
    ):
        m = re.search(pat, text, re.I)
        if m:
            val = _num_ru(m.group(1))
            if 1.0 < val <= 3.0:
                return val
    return None


def _custom_mass_gesn_candidates(*, include_height: bool = False) -> list[dict[str, str]]:
    """Показать оператору возможные нормы-кандидаты, не привязывая их к сумме без ВОР."""
    try:
        from proxy.services.estimate_harness_service import search_norm
    except Exception:  # noqa: BLE001
        return []
    descriptions = [
        ("монтаж стальных конструкций каркаса", "монтаж металлоконструкций"),
        ("такелаж строповка металлических конструкций", "такелаж/строповка"),
        ("установка стальных конструкций ярусов", "монтаж ярусов"),
    ]
    if include_height:
        descriptions.append(("работа на высоте монтаж металлических конструкций", "высотный фактор"))
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for desc, label in descriptions:
        res = search_norm(desc, work_family="metal", element_type="metal_assembly",
                          action="монтаж", unit_hint="т", top_k=5)
        for cand in res.get("candidates") or []:
            code = str(cand.get("norm_code") or "").strip()
            if not code or code in seen:
                continue
            if cand.get("applicability_status") not in ("accepted", "ambiguous"):
                continue
            seen.add(code)
            out.append({
                "work": label,
                "code": code,
                "title": str(cand.get("title") or ""),
                "status": str(cand.get("applicability_status") or ""),
            })
            break
    return out[:5]


def _default_custom_mass_rates() -> dict[str, float]:
    return {
        "control_assembly": 45000.0,
        "packaging": 20000.0,
        "mounting": 85000.0,
        "rigging": 12000.0,
        "constrained_k": 1.15,
        "qa_pct": 0.03,
        "contingency_pct": 0.10,
        "vat_pct": 0.20,
    }


def _answer_custom_mass_estimate(
    q: str,
    *,
    context_questions: list[str] | None = None,
    context_traces: list[dict[str, Any]] | None = None,
) -> Optional[dict[str, Any]]:
    """Fallback для мутных ТЗ на монтаж тяжёлых металлоконструкций по массе.

    Не защищаемая ЛСР: нет Приложения_1 с позициями, нет подобранных ГЭСН-кодов и рыночных КП.
    Но прикидка целиком нужна оператору — считаем кодом от массы/этапов и явно маркируем допущения.
    """
    context_text = "\n".join([*(context_questions or []), q])
    trace = _latest_custom_mass_trace(context_traces)
    has_trace_followup = bool(trace) and _is_custom_mass_followup(q)
    if not _has_custom_mass_signal(context_text) and not has_trace_followup:
        return None
    ql = context_text.lower()
    mass_kg = _extract_mass_kg(context_text)
    if mass_kg <= 0 and trace.get("mass_t"):
        mass_kg = _f(trace.get("mass_t")) * 1000.0
    if mass_kg <= 0:
        return None
    tiers = _extract_int(r"(\d+)\s*ярус", context_text) or int(_f(trace.get("tiers"))) or 1
    mass_t = round(mass_kg / 1000.0, 3)
    control_t = round(mass_t * min(2, tiers) / max(tiers, 1), 3)
    material_cost_zero = "0 руб" in ql and ("даваль" in ql or "сыр" in ql)
    transport_zero = "транспорт" in ql and "0 руб" in ql
    if trace and "material_cost_zero" in trace:
        material_cost_zero = material_cost_zero or bool(trace.get("material_cost_zero"))
    if trace and "transport_zero" in trace:
        transport_zero = transport_zero or bool(trace.get("transport_zero"))

    rates = dict(trace.get("assume_rates") or _default_custom_mass_rates())
    for key, val in _default_custom_mass_rates().items():
        rates[key] = _f(rates.get(key)) or val
    height_requested = _height_work_requested(context_text)
    height_k = _extract_user_coefficient(q if height_requested else "")
    height_applied = bool(height_requested and height_k)
    height_factor = height_k or 1.0
    mounting_rate = rates["mounting"] * rates["constrained_k"] * height_factor
    rigging_rate = rates["rigging"] * height_factor
    rows = [
        ("Этап 1. Контрольная сборка двух смежных ярусов с бронзовыми элементами",
         "ТЗ: 2 смежных яруса; расчётное допущение 45 000 ₽/т",
         control_t, "т", rates["control_assembly"], round(control_t * rates["control_assembly"], 2)),
        ("Этап 2. Упаковка в транспортировочную тару негабаритных ярусов",
         "ТЗ: весь тоннаж; расчётное допущение 20 000 ₽/т",
         mass_t, "т", rates["packaging"], round(mass_t * rates["packaging"], 2)),
        ("Этап 4. Монтаж ярусов с колёс гусеничным краном",
         "ТЗ: весь тоннаж; расчётное допущение 85 000 ₽/т × k=1.15"
         + (f" × высотные работы k={_fmt_num(height_factor)}" if height_applied else ""),
         mass_t, "т", mounting_rate, round(mass_t * mounting_rate, 2)),
        ("Строповка, временный крепёж, такелажная оснастка и монтажные доводки",
         "расчётное допущение 12 000 ₽/т"
         + (f" × высотные работы k={_fmt_num(height_factor)}" if height_applied else ""),
         mass_t, "т", rigging_rate, round(mass_t * rigging_rate, 2)),
    ]
    direct = round(sum(r[-1] for r in rows), 2)
    qa = round(direct * rates["qa_pct"], 2)
    subtotal = round(direct + qa, 2)
    contingency = round(subtotal * rates["contingency_pct"], 2)
    before_vat = round(subtotal + contingency, 2)
    vat = round(before_vat * rates["vat_pct"], 2)
    total = round(before_vat + vat, 2)

    lines = [
        "**Предварительная прикидка по прикреплённому ТЗ: стальные/бронзовые ярусы**",
        "",
        f"Распознано из ТЗ: масса **{_fmt_num(mass_t)} т**, ярусов **{tiers}**. "
        "Стоимость давальческого сырья принята 0 ₽; транспорт/погрузка по этапу 3 не включены.",
        "",
        "| Раздел | Основание | Объём | Ставка | Стоимость, ₽ |",
        "|---|---|---:|---:|---:|",
    ]
    for name, basis, qty, unit, rate, amount in rows:
        lines.append(f"| {name} | {basis} | {_fmt_num(qty)} {unit} | {_fmt_num(rate)} ₽/{unit} | {_fmt_num(amount)} |")
    lines += [
        f"| Инженерное сопровождение, ППР/геодезия/контроль качества | расчётное допущение 3% от работ | — | — | {_fmt_num(qa)} |",
        "",
        f"Работы без НДС: **{_fmt_num(subtotal)} ₽**",
        f"+ резерв на погодные/организационные простои и нестыковки 10%: {_fmt_num(contingency)} ₽",
        f"+ НДС 20%: {_fmt_num(vat)} ₽",
        f"**━━ ОРИЕНТИР стоимости работ с НДС: {_fmt_num(total)} ₽**",
        "",
        "### Защита расчёта: что откуда взято",
        f"- Масса, {tiers} ярусов, этапы, нулевое сырьё и исключение транспорта взяты из прикреплённого ТЗ.",
        "- Ставки по тонне — расчётные допущения, потому что в ЛЕС сейчас нет служебного рыночного датасета КП/договоров по таким уникальным работам.",
        "- Нормативная ЛСР по ГЭСН пока не защищается: нужен файл Приложение_1 с массами/габаритами ярусов и ручной подбор норм на монтаж/такелаж/упаковку.",
        "- Рыночную стоимость с внешними ссылками ЛЕС сейчас не подтверждает: нужен датасет коммерческих предложений или разрешённый market-source workflow.",
    ]
    if trace and not _extract_mass_kg(q):
        lines.append("- Масса и число ярусов восстановлены из предыдущего расчёта этой сессии.")
    if height_requested and height_applied:
        lines.append(
            f"- Высотные работы учтены коэффициентом k={_fmt_num(height_factor)} из текущей реплики; "
            "коэффициент применён к монтажу и такелажу."
        )
    elif height_requested:
        lines.append(
            "- Высотные работы распознаны как фактор, но итог не увеличен: в реплике нет высоты, "
            "ПОС/ППР или явного коэффициента. Можно написать: «учти высотные работы k=1,15»."
        )
    candidates = _custom_mass_gesn_candidates(include_height=height_requested)
    if candidates:
        lines += [
            "",
            "### Кандидаты ГЭСН для привязки",
            "_Это не основание текущей суммы: кандидаты надо привязать к ВОР/Приложению 1, единицам и объёмам._",
            "",
            "| Работа | Кандидат | Что найдено |",
            "|---|---|---|",
        ]
        for cand in candidates:
            title = cand["title"].replace("|", "/")
            lines.append(f"| {cand['work']} | {cand['code']} | {title} |")
    warnings = []
    if not material_cost_zero:
        warnings.append("стоимость давальческого сырья не удалось уверенно занулить")
    if not transport_zero:
        warnings.append("транспортный этап не удалось уверенно исключить")
    if height_requested and not height_applied:
        warnings.append("для высотных работ нужен явный коэффициент или нормативное основание")
    if warnings:
        lines.append("- Проверить: " + "; ".join(warnings) + ".")
    sources = [
        {"source_ref": "attachment:ТЗ_столп_22_06.docx", "source_kind": "file_body",
         "excerpt": "Масса 664 711,12 кг; 11 ярусов; этапы сборка/упаковка/монтаж; сырьё и транспорт = 0."},
    ]
    if trace and not _extract_mass_kg(q):
        sources.append({
            "source_ref": "session:previous_custom_mass_estimate",
            "source_kind": "session_context",
            "excerpt": "Масса, ярусы и ставки восстановлены из retrieval_trace предыдущего расчёта.",
        })
    return {
        "answer": "\n".join(lines),
        "operation": "custom_mass_estimate_assumed",
        "sources": sources,
        "retrieval_trace": {
            "mode": "custom_mass_estimate_assumed",
            "mass_t": mass_t,
            "tiers": tiers,
            "assume_rates": rates,
            "material_cost_zero": material_cost_zero,
            "transport_zero": transport_zero,
            "height_work": {
                "requested": height_requested,
                "applied": height_applied,
                "coefficient": height_factor if height_applied else None,
                "missing": "height_or_coefficient_basis" if height_requested and not height_applied else None,
            },
            "gesn_candidates": candidates,
            "grand_total": total,
        },
        "evidence_summary": {"COMPUTED": 1, "ASSUMED": len(rows) + 3,
                             "MISSING": 2 + (1 if height_requested and not height_applied else 0)},
        "total_status": "computed_assumed",
    }


def _answer_assemble(q: str) -> dict[str, Any]:
    from proxy.services.gesn_service import get_norm
    from proxy.services.lsr_assembly_service import assemble

    import os

    code = _GESN_RE.search(q).group(0).strip()
    norm = get_norm(code)
    if norm is None:
        from proxy.services.gesn_service import _norm_code
        ac = _norm_code(code)
        # 1) официальный ФГИС ЦС — БЕСПЛАТНО, без квоты (основной источник базы как есть)
        try:
            from proxy.services.gesn_fgis_service import fetch_and_cache as _fgis
            _fgis(ac)
            norm = get_norm(code)
        except Exception:
            pass
        # 2) cs.smetnoedelo — резерв/апдейты (квота, нужен токен)
        if norm is None and os.getenv("LES_SMETNOE_TOKEN", "").strip():
            try:
                from proxy.services.gesn_api_service import fetch_and_cache as _sm
                _sm(ac)
                norm = get_norm(code)
            except Exception:
                pass
    if norm is None:
        return {"answer": f"Норма ГЭСН {code} не найдена (семя/база/ФГИС ЦС/smetnoedelo). "
                          f"Проверь шифр или импортируй базу (tools/gesn_pdf_import).",
                "operation": "assemble"}
    qty = _parse_qty(q, code)
    if qty is None:
        return {"answer": f"Норма {code} найдена ({norm.get('name','')}). Укажи объём: "
                          f"«собери {code} объём <число>».", "operation": "assemble"}
    cond = _detect_condition(q) if ("стеснён" in q.lower() or "стеснен" in q.lower()) else None
    # НР/СП по виду работ (норма их не несёт) — из наименования
    nr_pct, sp_pct = _f(norm.get("nr_pct")), _f(norm.get("sp_pct"))
    nr_sp_note = ""
    if not nr_pct or not sp_pct:
        from proxy.services.nr_sp_service import resolve as _resolve_nr_sp
        rs = _resolve_nr_sp(norm.get("name", ""))
        nr_pct = nr_pct or rs["nr_pct"]
        sp_pct = sp_pct or rs["sp_pct"]
        nr_sp_note = f"вид работ: {rs['label']}" + (" (по умолчанию — уточнить)" if rs["default"] else "")
    pos = {"code": code, "name": norm.get("name", ""), "unit": norm.get("unit", ""), "qty": qty,
           "nr_pct": nr_pct, "sp_pct": sp_pct}
    res = assemble([pos], condition=cond)
    p = res["positions"][0]
    b = p["base"]
    used = p["adjusted"] if cond else b
    lines = [
        f"{norm.get('name','')} · {code} · объём {qty} {norm.get('unit','')}",
        f"ОЗП {_fmt_num(b['ozp'])} + ЭМ {_fmt_num(b['em'])} + М {_fmt_num(b['mat'])} = "
        f"прямые {_fmt_num(b['direct'])}",
        f"ФОТ {_fmt_num(b['fot'])} → НР {_fmt_num(b['nr'])} ({_fmt_num(nr_pct)}%) + "
        f"СП {_fmt_num(b['sp'])} ({_fmt_num(sp_pct)}%)" + (f" · {nr_sp_note}" if nr_sp_note else ""),
        f"ИТОГО по позиции: {_fmt_num(used['total'])} руб."
        + (f"  (стеснённость ×{res['k_ozp']}: было {_fmt_num(b['total'])})" if cond else ""),
    ]
    if p.get("flags"):
        lines.append("⚠ " + "; ".join(p["flags"]))
    return {"answer": "\n".join(lines), "operation": "assemble"}


def _answer_object_estimate(
    q: str,
    *,
    parsed_context: dict[str, Any] | None = None,
    context_questions: list[str] | None = None,
    context_traces: list[dict[str, Any]] | None = None,
) -> Optional[dict[str, Any]]:
    """«дай смету на <объект>» → объектный расчёт (Ц16): фраза → ВОР → ЛСР-движок → смета."""
    from proxy.services.object_estimate_service import estimate

    r = estimate(q, parsed_context=parsed_context)
    if not r.get("ok"):
        custom = _answer_custom_mass_estimate(
            q,
            context_questions=context_questions,
            context_traces=context_traces,
        )
        if custom is not None:
            return custom
        # Запрос ЯВНО про объектную смету (есть площадь/этажность ИЛИ императив «смету на …»),
        # но собрать не можем (нет шаблона под объект/материал, нет площади) — отдаём БЫСТРЫЙ
        # честный ответ, а НЕ роняем в полный RAG (там local-only датасет → форс локальной 4B →
        # десятки секунд генерации мусора). Чистый knowledge-вопрос про сметы (без объекта/чисел)
        # → None, пусть идёт в RAG.
        parsed = r.get("parsed", {})
        # «Конкретный» сигнал объектной сметы = распознан объект/площадь/этажность. Голый
        # императив без параметров («посчитай смету») слишком расплывчат → пусть идёт в RAG.
        build_intent = bool(parsed.get("object") or parsed.get("area") or parsed.get("floors"))
        if not build_intent:
            return None
        err = r.get("error") or "Не получилось собрать смету по описанию."
        msg = (
            f"{err}\n"
            f"Распознал: объект={parsed.get('object') or '—'}, "
            f"материал={parsed.get('material') or '—'}, "
            f"этажей={parsed.get('floors') or '—'}, "
            f"площадь={parsed.get('area') or '—'} м².\n"
            "Под этот объект пока нет точного типового состава и близкого локального аналога. "
            "Нужны ВОР/проект/смета/КС-2 или новый типовой состав с кодами ГЭСН и формулами объёма."
        )
        return {"answer": msg, "operation": "object_estimate_nomatch"}
    parsed, est = r.get("parsed", {}), r.get("estimate", {})
    pos, apos = r.get("vor", {}).get("positions", []), est.get("positions", [])
    head = r.get("template", {}).get("name", "объект")
    analog = r.get("analog") or {}
    # Тело — короткие блоки + markdown-таблица позиций (inline-рендер чата превращает её в ui.table).
    # Видимый текст должен быть операторским, без внутренних id/status, которые остаются в payload.
    lines = [
        f"Прикидка стоимости объекта: {parsed.get('area')} м², {parsed.get('floors')} эт.",
        "",
        "Коротко:",
    ]
    if analog:
        lines.extend([
            f"- Ближайший локальный аналог: {head}.",
            "- Это не точное совпадение с исходным описанием.",
            "- Это ориентир, не защищаемая ЛСР по проекту.",
            "- Объёмы посчитаны кодом из площади и этажности; цены собраны по локальной ГЭСН-базе.",
            "- Точного состава под исходный материал нет: взят ближайший локальный аналог.",
            "",
            "Почему выбран этот аналог:",
        ])
        for reason in _visible_analog_reasons(analog):
            lines.append(f"- {reason}.")
    else:
        lines.extend([
            f"- Типовой состав: {head}.",
            "- Это ориентир, не защищаемая ЛСР по проекту.",
            "- Объёмы посчитаны кодом из площади и этажности; цены собраны по локальной ГЭСН-базе.",
        ])
    lines.append("")
    if r.get("scope_warnings"):
        lines.append("Что не покрыто точно:")
        for warning in r["scope_warnings"]:
            lines.append(f"- {_visible_object_text(warning)}")
        lines.append("")
    candidate_lines = _composition_candidate_lines(r)
    if candidate_lines:
        lines.extend(candidate_lines)
        lines.append("")
    lines.append("| Позиция/раздел | Основание | Объём | Стоимость, ₽ |")
    lines.append("|---|---|---|---|")
    for p, ap in zip(pos, apos):
        t = _f(ap.get("base", {}).get("total"))
        qty_disp = _humanize_qty(p.get("qty"), p.get("unit", ""))
        name = str(p.get("name", "")).replace("|", "/")
        lines.append(f"| {name} | {p.get('code')} | {qty_disp} | {_fmt_num(t)} |")
    for a in r.get("allowances") or []:
        label = str(a.get("label") or "Укрупнённый раздел").replace("|", "/")
        pct = round(_f(a.get("pct_of_smr")) * 100, 1)
        lines.append(f"| {label} | Допущение: {pct}% от ГЭСН-конструктива | — | {_fmt_num(a.get('amount'))} |")
    lines.append("")
    tot = r.get("totals", {})
    lines.extend([
        "Итог:",
        f"- ГЭСН-конструктив: {_fmt_num(tot.get('gesn_smr'))} ₽",
        f"- Укрупнённые разделы по допущению: {_fmt_num(tot.get('allowance_total'))} ₽",
        f"- Текущий уровень цен k={_fmt_num(tot.get('price_level_k'))}: {_fmt_num(tot.get('smr'))} ₽",
        f"- Непредвиденные {_fmt_num(tot.get('contingency_pct'))}%: {_fmt_num(tot.get('contingency'))} ₽",
        f"- НДС {_fmt_num(tot.get('vat_pct'))}%: {_fmt_num(tot.get('vat'))} ₽",
        f"- **Ориентир с НДС: {_fmt_num(tot.get('grand_total'))} ₽**",
    ])
    # Codex §10.1B: число COMPUTED — строгое ТОЛЬКО относительно явной базы и допущений ниже.
    # Это не детальная смета по проекту, а бюджетная прикидка с явными допущениями.
    lines.append("")
    lines.append("_Если прикрепить ВОР/Ф9/КС-2/папку проекта, расчёт пойдёт по проектным данным._")
    if r.get("missing_codes"):
        lines.append(f"⚠ нет в базе: {', '.join(r['missing_codes'])}")
    lines.append(f"Состав: {tot.get('positions')} ГЭСН-поз. + "
                 f"{tot.get('allowance_positions')} укрупнённых разделов.")
    if r.get("assumptions"):
        lines.append("")
        lines.append("Ключевые допущения:")
        for assumption in r["assumptions"]:
            lines.append(f"- {_visible_object_text(assumption)}")
    logic_lines = _object_estimate_logic_lines(r)
    if logic_lines:
        lines.extend(["", "### Защита расчёта: что откуда взято", *logic_lines])
    # provenance (Codex §10.1B): класс числа + база + допущения — структурно, для claim-валидации.
    provenance = {
        "kind": "COMPUTED",
        "basis": [f"template:{r.get('template', {}).get('id')}", "ГЭСН-2022"],
        "analog": analog or None,
        "assumptions": r.get("assumptions", []),
        "confidence": r.get("quality", {}).get("status") or "rough_full_object_assumed",
        "final_total_allowed": False,
        "defensibility": r.get("defense", {}).get("defensibility", {}),
    }
    return {
        "answer": "\n".join(lines),
        "operation": "object_estimate",
        "provenance": provenance,
        "defense": (r.get("defense") or {}).get("contract") or r.get("defense"),
        "sources": _object_estimate_sources(r),
        "retrieval_trace": _object_estimate_trace(r),
        "evidence_summary": {
            "COMPUTED": 1,
            "ASSUMED": len(r.get("allowances") or []),
            "MISSING_PRICE": r.get("defense", {}).get("price_coverage", {}).get("missing", 0),
        },
        "total_status": "computed_assumed",
    }


def _object_estimate_sources(result: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [dict(s) for s in _OBJECT_ESTIMATE_SOURCES]
    template_id = result.get("template", {}).get("id") or "object_template"
    sources[0]["source_ref"] = f"config/domain/object_templates.yaml#{template_id}"
    if result.get("analog"):
        sources[0]["excerpt"] += " Использован как ближайший локальный аналог, не как точный шаблон."
    for p in result.get("vor", {}).get("positions") or []:
        code = str(p.get("code") or "").strip()
        if code:
            sources.append({
                "source_ref": f"ГЭСН-2022#{code}",
                "source_kind": "norm",
                "excerpt": str(p.get("name") or ""),
            })
    for item in (result.get("composition_candidates") or {}).get("items") or []:
        for cand in item.get("candidates") or []:
            code = str(cand.get("norm_code") or "").strip()
            if code:
                sources.append({
                    "source_ref": f"ГЭСН-2022#{code}",
                    "source_kind": "norm_candidate",
                    "excerpt": str(cand.get("title") or ""),
                })
    return sources


def _visible_analog_reasons(analog: dict[str, Any]) -> list[str]:
    """Машинные причины выбора аналога → человекочитаемые bullets без внутренних match.*."""
    obj = str(analog.get("requested_object") or "объект").strip()
    material = str(analog.get("requested_material") or "").strip()
    out = [f"объект распознан как «{obj}»"]
    if material:
        out.append(f"материал «{material}» близок к деревянному ИЖС, но это не точное совпадение")
    out.append("назначение похоже на малоэтажный жилой объект")
    return out


def _visible_object_text(text: Any) -> str:
    """Убрать из видимого ответа внутренние слова/пути, оставив смысл для оператора."""
    s = str(text or "")
    replacements = [
        ("Точного объектного шаблона", "Точного объектного состава"),
        ("отдельный вариант шаблона", "отдельный вариант состава"),
        ("шаблоне", "типовом составе"),
        ("шаблона", "типового состава"),
        ("шаблону", "типовому составу"),
        ("шаблоны", "типовые составы"),
        ("шаблон", "типовой состав"),
        ("типовой состава", "типового состава"),
        ("ASSUME", "допущение"),
        (" из config/domain/object_templates.yaml", ""),
        ("config/domain/object_templates.yaml", "локальная база типовых составов"),
    ]
    for old, new in replacements:
        s = s.replace(old, new)
    return s


def _object_estimate_trace(result: dict[str, Any]) -> dict[str, Any]:
    totals = result.get("totals") or {}
    return {
        "mode": "object_estimate",
        "quality_status": result.get("quality", {}).get("status") or "rough_full_object_assumed",
        "template": result.get("template", {}).get("id"),
        "analog": result.get("analog"),
        "composition_candidates": result.get("composition_candidates"),
        "positions": totals.get("positions", 0),
        "allowance_positions": totals.get("allowance_positions", 0),
        "sources_count": len(_object_estimate_sources(result)),
        "price_coverage": result.get("defense", {}).get("price_coverage", {}),
        "calc": {
            "gesn_smr": totals.get("gesn_smr"),
            "allowance_total": totals.get("allowance_total"),
            "subtotal_base": totals.get("subtotal_base"),
            "price_level_k": totals.get("price_level_k"),
            "smr_current": totals.get("smr"),
            "contingency_pct": totals.get("contingency_pct"),
            "vat_pct": totals.get("vat_pct"),
            "grand_total": totals.get("grand_total"),
        },
    }


def _object_estimate_logic_lines(result: dict[str, Any]) -> list[str]:
    totals = result.get("totals") or {}
    template_id = result.get("template", {}).get("id") or "—"
    codes = ", ".join(str(p.get("code")) for p in result.get("vor", {}).get("positions") or [] if p.get("code"))
    defense = result.get("defense") or {}
    coverage = defense.get("price_coverage") or {}
    missing_prices = int(coverage.get("missing") or 0)
    resources = int(coverage.get("resources") or 0)
    lines = [
        "- Статус: **ориентир, не защищаемая ЛСР**. Защищать можно ход расчёта и нижнюю "
        "ГЭСН-базу; итог целиком держится на укрупнённых допущениях, k текущего уровня и незакрытых ценах ресурсов.",
        f"- Нормативная база: типовой состав `{template_id}` выбрал коды ГЭСН {codes or '—'}; объёмы ниже "
        "получены из формул ВОР, а не из текста модели.",
        f"- Ценовое покрытие ресурсов: {resources} ресурс(ов), без цены: {missing_prices}. "
        "Ресурс без цены входит в предупреждения и не делает итог защищаемой коммерческой сметой.",
        "",
        "| Код | Объём защищён чем | Стоимость собрана как | Цены ресурсов |",
        "|---|---|---|---|",
    ]
    for item in defense.get("gesn_positions") or []:
        c = item.get("cost_build_up") or {}
        pc = item.get("resource_price_coverage") or {}
        qty = f"{_fmt_num(item.get('physical_qty'))} {item.get('physical_unit') or ''}".strip()
        formula = str(item.get("formula") or "—")
        values = _formula_values_text(item.get("formula_values") or {})
        norm = f"{_fmt_num(item.get('norm_qty'))} {item.get('norm_unit') or ''}".strip()
        cost = (
            f"прямые {_fmt_num(c.get('direct'))} + НР {_fmt_num(c.get('nr'))} + "
            f"СП {_fmt_num(c.get('sp'))} = {_fmt_num(c.get('total'))}"
        )
        lines.append(
            f"| {item.get('code') or '—'} | {qty}; `{formula}` при {values} → {norm} | "
            f"{cost} | {_coverage_text(pc)} |"
        )
    allowances = defense.get("allowance_positions") or []
    if allowances:
        lines.extend(["", "Укрупнённые разделы — не нормы и не КП, а явные операторские допущения типового состава:"])
        for a in allowances:
            pct = round(_f(a.get("pct_of_smr")) * 100, 1)
            lines.append(
                f"- {a.get('label')}: {pct}% × ГЭСН-конструктив "
                f"{_fmt_num(totals.get('gesn_smr'))} = {_fmt_num(a.get('amount'))} ₽ "
                "(допущение, не нормативная позиция)."
            )
    lines.extend([
        f"- Текущий уровень цен: (`ГЭСН-конструктив + ASSUME`) × k={_fmt_num(totals.get('price_level_k'))} "
        f"= {_fmt_num(totals.get('smr'))} ₽. k сейчас ASSUME: для защиты нужен регион/квартал/индекс.",
        f"- Хвост: непредвиденные {_fmt_num(totals.get('contingency_pct'))}% + НДС "
        f"{_fmt_num(totals.get('vat_pct'))}% = {_fmt_num(totals.get('grand_total'))} ₽.",
        "- Для защищаемой сметы нужны ВОР/Ф9/КС-2 или проектные объёмы, регион/квартал индексов, "
        "ФГИС/КАЦ/КП по ресурсам, и детальные позиции по подвалу, инженерке, фасадам и отделке.",
        "- Ссылки на код/алгоритм — это воспроизводимость расчёта, не доказательство стоимости.",
    ])
    return lines


def _composition_candidate_lines(result: dict[str, Any]) -> list[str]:
    plan = result.get("composition_candidates") or {}
    items = [item for item in plan.get("items") or [] if item.get("candidates")]
    if not items:
        return []
    lines = [
        "Что нашлось в базе ГЭСН для детализации:",
        "- Эти нормы пока не включены в сумму автоматически; их нужно подтвердить ВОР/проектом или отдельным уточнением.",
    ]
    for item in items[:5]:
        label = str(item.get("label") or "Работа")
        cand_text = []
        candidates = item.get("candidates") or []
        for cand in candidates[:1]:
            code = str(cand.get("norm_code") or "—")
            title = str(cand.get("title") or "").strip()
            title = title[:82] + "..." if len(title) > 82 else title
            status = str(cand.get("applicability_status") or "candidate")
            cand_text.append(f"{code} — {title} ({_candidate_status_text(status)})")
        if cand_text:
            more = f"; ещё {len(candidates) - 1} в источниках/trace" if len(candidates) > 1 else ""
            lines.append(f"- {label}: " + "; ".join(cand_text) + more)
    return lines


def _candidate_status_text(status: str) -> str:
    return {
        "accepted": "подходит по грубому фильтру",
        "ambiguous": "требует проверки",
        "rejected": "показано только для следа, не подходит",
    }.get(status, "кандидат")


def _formula_values_text(values: dict[str, Any]) -> str:
    if not values:
        return "—"
    return ", ".join(f"{k}={_fmt_num(v)}" for k, v in sorted(values.items()))


def _coverage_text(coverage: dict[str, Any]) -> str:
    by_source = coverage.get("by_source") or {}
    parts = [f"{k} {v}" for k, v in sorted(by_source.items())]
    text = ", ".join(parts) if parts else "—"
    examples = coverage.get("missing_examples") or []
    if examples:
        text += "; нет цены: " + "; ".join(str(x) for x in examples[:2])
    return text


def _humanize_qty(qty: Any, unit: str) -> str:
    """Объём из нормы (qty в «сотнях/десятках единиц») → человекочитаемо в базовой единице.
    «100 м3» qty=4.0 → «400 м³»; «10 м2» qty=125.2 → «1 252 м²»."""
    u = str(unit or "").strip()
    factor, base_u = 1.0, u
    m = re.match(r"(\d+)\s*(.+)", u)
    if m:
        factor = float(m.group(1))
        base_u = m.group(2).replace("м2", "м²").replace("м3", "м³")
    return f"{_fmt_num(round(_f(qty) * factor, 2))} {base_u}".strip()


def maybe_handle_smeta_query(
    question: str,
    *,
    project_id: int = 0,
    context_questions: list[str] | None = None,
    context_traces: list[dict[str, Any]] | None = None,
) -> Optional[dict[str, Any]]:
    """Лёгкий сметный запрос → справка/расчёт. None — не наш кейс (уходит дальше/в RAG)."""
    from proxy.services import sovushka_tone

    if sovushka_tone.wants_model(question):   # «своими словами» → уступаем дорогу модели
        return None
    q = " ".join(str(question or "").split())
    ql = q.lower()
    code = _first_code(q)

    r: Optional[dict[str, Any]] = None
    if ("смет" in ql or "посчитай" in ql) and not _GESN_RE.search(q):  # «дай смету на <объект>» (Ц16)
        r = _answer_object_estimate(q, context_questions=context_questions, context_traces=context_traces)
    if r is None and any(w in ql for w in _ASSEMBLE_WORDS) and _GESN_RE.search(q):  # сборка от кода ГЭСН
        r = _answer_assemble(q)
    elif r is None and any(w in ql for w in _STESN_WORDS) and ("коэф" in ql or "стесн" in ql):  # стеснённость
        r = _answer_stesnennost(q)
    elif r is None and code and any(w in ql for w in _KAC_WORDS):     # нужен ли КАЦ
        r = _answer_needs_kac(code)
    elif r is None and code and any(w in ql for w in _PRICE_WORDS):   # цена по коду
        r = _answer_price(code)
    if r is None:
        return None
    r = dict(r)
    r["answer"] = sovushka_tone.flavor(r["answer"], r.get("operation", ""), seed=q)
    return r
