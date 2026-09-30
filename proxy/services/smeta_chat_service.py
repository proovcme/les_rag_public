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

    book_path = fps.resolve_pricebook_path()
    if not book_path:
        return {"answer": f"Код {code}: нет книги цен ФГИС ЦС — импортируйте «Сплит-форму» "
                          f"(Инструменты → ФГИС ЦС).",
                "operation": "price"}
    pb = fps.get_pricebook(book_path)
    rec = pb.lookup(code)
    if rec is None:
        return {"answer": f"Код {code} не найден в ФГИС ЦС ({pb.region} {pb.quarter}). "
                          f"Если материал отсутствует в базе — нужен КАЦ (≥3 КП на материал).",
                "operation": "price"}
    return {"answer": (f"{rec.get('name','')} · {rec.get('unit','')}\n"
                       f"Сметная цена (текущая): {_fmt_num(rec.get('price_current_eff'))} руб. "
                       f"(базовая {_fmt_num(rec.get('price_base'))} × индекс {rec.get('index')})\n"
                       f"{pb.region} · {pb.quarter} · книга {Path(book_path).stem}"),
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
    from proxy.smeta_core.calculator import calculate_scenario
    from proxy.smeta_core.contracts import NormBinding, WorkItem

    code = _GESN_RE.search(q).group(0).strip()
    if not re.match(r"^(?:ГЭСН(?:мр|м|п|р)?|ФЕР(?:мр|м|п|р)?|ТЕР(?:мр|м|п|р)?)", code, re.I):
        return {
            "answer": f"Для расчёта нужен полный шифр с типом базы, например ГЭСНм{code}. "
            "Код не будет угадывать семейство нормы по голому номеру.",
            "operation": "assemble",
            "evidence_status": "partial",
            "calculation_status": "not_calculated",
        }
    norm = get_norm(code)
    if norm is None:
        return {
            "answer": f"Норма {code} не найдена в локальной trusted machine base. Расчёт не запускался.",
            "operation": "assemble",
            "evidence_status": "partial",
            "calculation_status": "not_calculated",
        }
    qty = _parse_qty(q, code)
    if qty is None:
        return {"answer": f"Норма {code} найдена ({norm.get('name','')}). Укажи объём: "
                          f"«собери {code} объём <число>».",
                "operation": "assemble",
                "evidence_status": "partial",
                "calculation_status": "not_calculated"}
    measure = re.match(r"\s*(\d+(?:[.,]\d+)?)?\s*(.+?)\s*$", str(norm.get("unit") or ""))
    card_basis = (measure.group(1) or "").replace(",", ".") if measure else ""
    physical_unit = measure.group(2) if measure else str(norm.get("unit") or "")
    scenario = calculate_scenario(
        [WorkItem(work_id="quick-1", title=str(norm.get("name") or code), quantity=qty, unit=physical_unit)],
        [NormBinding(
            work_id="quick-1",
            norm_code=code,
            selected_by="user",
            selection_kind="exact",
            is_analog=False,
            reason="полный шифр указан пользователем",
        )],
        title=str(norm.get("name") or code),
    )
    trace = scenario.trace
    positions = [position for section in trace.get("sections") or [] for position in section.get("positions") or []]
    p = positions[0] if positions else {"summary": {}}
    b = p.get("summary") or {}
    # «объём 61» is the physical volume the operator named, and the calculator already
    # rescaled it to the card; printing the card's own «100 м2» next to 61 would tell the
    # operator the money below was counted from 61 cards.  Both units stay visible instead.
    card_measure_note = (
        f" (карточка нормы — на {norm.get('unit')})"
        if card_basis and card_basis != "1"
        else ""
    )
    # Та же сумма в доставленном документе подписана формой иначе: `rim_lsr_trace_service`
    # пишет «Всего по позиции» только когда `full_amount` закрыт, и «Известная стоимость
    # позиции» — когда есть незакрытое основание (цена, НР/СП, ФСЭМ, коэффициент).  Чат
    # печатал «ИТОГО по позиции» в обоих случаях, то есть называл итогом число, которое
    # строкой ниже сам же помечал пробелом.  Знак берётся у трассы, а не придумывается.
    amount_status = str(b.get("amount_status") or scenario.calculation_status.value)
    known = b.get("known_amount")
    total_label = "Всего по позиции" if amount_status == "complete" else "Известная стоимость позиции"
    total_amount = known if (amount_status != "complete" and known is not None) else b.get("total")
    lines = [
        f"{norm.get('name','')} · {code} · объём {qty} {physical_unit}{card_measure_note}",
        f"ОЗП {_fmt_num(b.get('ozp'))} + ЭМ {_fmt_num(b.get('em'))} + М {_fmt_num(b.get('mat'))} = "
        f"прямые {_fmt_num(b.get('direct'))}",
        f"ФОТ {_fmt_num(b.get('fot'))} → НР {_fmt_num(b.get('nr'))} + СП {_fmt_num(b.get('sp'))}",
        f"{total_label}: {_fmt_num(total_amount)} руб.",
    ]
    if b.get("flags"):
        lines.append("⚠ " + "; ".join(str(item) for item in b["flags"]))
    elif amount_status != "complete":
        # Незакрытая позиция без ⚠-флага молча выглядела бы готовой: печатаем основания
        # так, как их называет трасса, а не переводим в свою формулировку.
        reasons = [str(item) for item in (b.get("completeness_reasons") or []) if str(item)]
        lines.append("⚠ Позиция закрыта не полностью: " + (", ".join(reasons) or amount_status))
    if scenario.calculation_status.value == "unsafe_source":
        lines.append("⚠ Сумма является непроверенным черновиком: нормативная база в карантине.")
    return {
        "answer": "\n".join(lines),
        "operation": "assemble",
        "evidence_status": scenario.evidence_status.value,
        "calculation_status": scenario.calculation_status.value,
        "scenario": scenario.as_dict(),
    }


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
    if any(w in ql for w in _ASSEMBLE_WORDS) and _GESN_RE.search(q):  # сборка от кода ГЭСН
        r = _answer_assemble(q)
    elif r is None and any(w in ql for w in _STESN_WORDS) and ("коэф" in ql or "стесн" in ql):
        # Selection of an applicable coefficient belongs to the model/user and must
        # be based on project conditions. The deterministic channel does not guess it.
        return None
    elif r is None and code and any(w in ql for w in _KAC_WORDS):     # нужен ли КАЦ
        r = _answer_needs_kac(code)
    elif r is None and code and any(w in ql for w in _PRICE_WORDS):   # цена по коду
        r = _answer_price(code)
    if r is None:
        return None
    r = dict(r)
    # Тон обязан знать статус расчёта: без `status` слой мог напечатать «цифры выверены —
    # можешь не перепроверять» над позицией со статусом `partial`.
    r["answer"] = sovushka_tone.flavor(
        r["answer"], r.get("operation", ""), seed=q, status=r.get("calculation_status")
    )
    return r
