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


def _answer_object_estimate(q: str) -> Optional[dict[str, Any]]:
    """«дай смету на <объект>» → объектный расчёт (Ц16): фраза → ВОР → ЛСР-движок → смета."""
    from proxy.services.object_estimate_service import estimate

    r = estimate(q)
    if not r.get("ok"):
        return None                                   # объект не распознан → дальше/в RAG
    parsed, est = r.get("parsed", {}), r.get("estimate", {})
    pos, apos = r.get("vor", {}).get("positions", []), est.get("positions", [])
    head = r.get("template", {}).get("name", "объект")
    lines = [f"Смета: {head} · {parsed.get('area')} м², {parsed.get('floors')} эт. "
             f"(укрупнённо, по типовому составу работ)"]
    for p, ap in zip(pos, apos):
        t = _f(ap.get("base", {}).get("total"))
        lines.append(f"• {str(p.get('name',''))[:44]} · {p.get('code')} · "
                     f"{p.get('qty')} {p.get('unit','')} — {_fmt_num(t)} ₽")
    tot = r.get("totals", {})
    lines.append(f"  ИТОГО СМР (прямые+НР+СП): {_fmt_num(tot.get('smr'))} ₽")
    lines.append(f"  + непредвиденные {_fmt_num(tot.get('contingency_pct'))}%: {_fmt_num(tot.get('contingency'))} ₽")
    lines.append(f"  + НДС {_fmt_num(tot.get('vat_pct'))}%: {_fmt_num(tot.get('vat'))} ₽")
    lines.append(f"━━ ВСЕГО (общая цена с НДС): {_fmt_num(tot.get('grand_total'))} ₽")
    if r.get("missing_codes"):
        lines.append(f"⚠ нет в базе: {', '.join(r['missing_codes'])}")
    lines.append(f"⚙ Состав укрупнённый ({tot.get('positions')} поз., типовой ИЖС) — "
                 f"отделка/проёмы/инженерка добавляются в шаблон.")
    if r.get("assumptions"):
        lines.append("Допущения: " + "; ".join(r["assumptions"])[:200])
    return {"answer": "\n".join(lines), "operation": "object_estimate"}


def maybe_handle_smeta_query(question: str, *, project_id: int = 0) -> Optional[dict[str, Any]]:
    """Лёгкий сметный запрос → справка/расчёт. None — не наш кейс (уходит дальше/в RAG)."""
    from proxy.services import sovushka_tone

    if sovushka_tone.wants_model(question):   # «своими словами» → уступаем дорогу модели
        return None
    q = " ".join(str(question or "").split())
    ql = q.lower()
    code = _first_code(q)

    r: Optional[dict[str, Any]] = None
    if ("смет" in ql or "посчитай" in ql) and not _GESN_RE.search(q):  # «дай смету на <объект>» (Ц16)
        r = _answer_object_estimate(q)
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
