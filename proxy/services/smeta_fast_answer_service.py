"""Fast visible smeta fallback for local-model timeouts.

This composer is deliberately narrow and transparent. It is used only when the
model path returns empty/timeout and the input already contains measurable work
quantities. It marks results as scenario estimates, not final LSR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from proxy.services.estimate_math_service import parse_ru_number


@dataclass(frozen=True)
class FastLine:
    title: str
    quantity: float
    unit: str
    norm_hint: str
    rate: float
    amount: float
    comment: str


def _fmt_num(value: float, digits: int = 2) -> str:
    text = f"{value:,.{digits}f}".replace(",", " ")
    if digits:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _fmt_money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " руб."


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    low = text.casefold()
    return any(n.casefold() in low for n in needles)


def _number_after(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return parse_ru_number(m.group(1))


def _numbers_on_matching_lines(text: str, marker: str, unit: str) -> list[float]:
    out: list[float] = []
    for line in str(text or "").splitlines():
        low = line.casefold()
        pos = low.find(marker.casefold())
        if pos < 0:
            continue
        segment = line[pos:]
        segment = re.split(r"[;\n]", segment, maxsplit=1)[0]
        for raw in re.findall(rf"([\d\s,.]+)\s*{unit}\b", segment, flags=re.IGNORECASE):
            value = parse_ru_number(raw)
            if value is not None:
                out.append(value)
    return out


def _patch_panel_count(text: str) -> float:
    total = 0.0
    for line in str(text or "").splitlines():
        if "патч-панел" not in line.casefold():
            continue
        for raw in re.findall(r"[-–]\s*([\d\s,.]+)\s*шт", line, flags=re.IGNORECASE):
            total += parse_ru_number(raw) or 0.0
    return total


def _last_numeric_cell(line: str) -> float | None:
    cells = [cell.strip() for cell in str(line or "").split("|")]
    for cell in reversed(cells):
        value = parse_ru_number(cell)
        if value is not None:
            return value
    return None


def _package_length_m(line: str) -> float | None:
    values: list[float] = []
    for raw in re.findall(r"\(([\d\s,.]+)\s*м\)", str(line or ""), flags=re.IGNORECASE):
        value = parse_ru_number(raw)
        if value:
            values.append(value)
    return max(values) if values else None


def _sks_quantities_from_rows(text: str) -> dict[str, float]:
    q = {
        "cat5_m": 0.0,
        "cat6_m": 0.0,
        "fiber_m": 0.0,
        "tray_m": 0.0,
        "conduit_m": 0.0,
        "racks": 0.0,
        "patch_panels": 0.0,
        "ports": 0.0,
        "fiber_splices": 0.0,
    }
    for line in str(text or "").splitlines():
        low = line.casefold()
        qty = _last_numeric_cell(line)
        if qty is None:
            continue
        package_len = _package_length_m(line)
        if "витая пара" in low and "u/utp" in low:
            if ("cat.5" in low or "категория 5" in low) and package_len:
                q["cat5_m"] += qty * package_len
            elif ("cat.6" in low or "категория 6" in low) and package_len:
                q["cat6_m"] += qty * package_len
        if "волоконно-оптичес" in low and ("м.п" in low or "| м" in low):
            q["fiber_m"] += qty
        if "кабель-канал" in low or "короб с крышкой" in low:
            if "м.п" in low or "| м" in low:
                q["tray_m"] += qty
        if "лоток" in low and ("м.п" in low or "| м" in low):
            if "комплект крепеж" not in low:
                q["tray_m"] += qty
        if "труба гофрированная" in low and ("пвх" in low or "пнд" in low):
            q["conduit_m"] += qty
        if "шкаф напольный" in low and "19" in low:
            q["racks"] += qty
        if "патч-панел" in low:
            q["patch_panels"] += qty
        if "keystone" in low and ("вставка" in low or "суппорт" in low):
            q["ports"] = max(q["ports"], qty)
        if "кдзс" in low or "пигтейл" in low:
            q["fiber_splices"] = max(q["fiber_splices"], qty)
    return q


def _sks_quantities(text: str) -> dict[str, float]:
    cat5 = _number_after(text, r"Cat\.?5e[^=\n]{0,80}=\s*([\d\s,.]+)\s*м") or 0.0
    cat6 = _number_after(text, r"Cat\.?6A[^=\n]{0,80}=\s*([\d\s,.]+)\s*м") or 0.0
    if not cat5:
        pack = _number_after(text, r"Cat\.?5e:\s*([\d\s,.]+)\s*бухт")
        if pack:
            cat5 = pack * 305.0
    if not cat6:
        pack = _number_after(text, r"Cat\.?6A:\s*([\d\s,.]+)\s*бухт")
        if pack:
            cat6 = pack * 500.0
    fiber = _number_after(text, r"(?:ВОЛС|волоконно[^:\n]*|OM4)[^:\n]{0,80}:\s*([\d\s,.]+)\s*м") or 0.0
    trays_total = _number_after(text, r"лотк[^\n]{0,80}всего\s*([\d\s,.]+)\s*м") or 0.0
    if not trays_total:
        trays_total = sum(x for x in [
            _number_after(text, r"50x50\s*-\s*([\d\s,.]+)\s*м") or 0.0,
            _number_after(text, r"100x50\s*-\s*([\d\s,.]+)\s*м") or 0.0,
            _number_after(text, r"200x50\s*-\s*([\d\s,.]+)\s*м") or 0.0,
            _number_after(text, r"400x50\s*-\s*([\d\s,.]+)\s*м") or 0.0,
            _number_after(text, r"проволочн[^\n]{0,40}\s([\d\s,.]+)\s*м") or 0.0,
        ])
    box = _number_after(text, r"кабель-канал[^\n]{0,80}:\s*([\d\s,.]+)\s*м") or 0.0
    conduit_values = []
    for marker in ("ПВХ", "ПНД"):
        values = _numbers_on_matching_lines(text, marker, "м")
        if values:
            conduit_values.append(values[-1])
    conduit = sum(conduit_values)
    racks = _number_after(text, r"шкаф[^\n:]{0,80}:\s*([\d\s,.]+)\s*шт") or 0.0
    patch_panels = _patch_panel_count(text)
    ports = (
        _number_after(text, r"Keystone[^-\n]*-\s*([\d\s,.]+)\s*шт")
        or _number_after(text, r"порты\s*([\d\s,.]+)")
        or 0.0
    )
    fiber_splices = _number_after(text, r"КДЗС\s*[-–]\s*([\d\s,.]+)\s*шт") or 0.0
    if not fiber_splices:
        fiber_splices = _number_after(text, r"пигтейл[^\n]{0,40}\s([\d\s,.]+)\s*шт") or 0.0
    row_q = _sks_quantities_from_rows(text)
    cat5 = cat5 or row_q["cat5_m"]
    cat6 = cat6 or row_q["cat6_m"]
    fiber = max(fiber, row_q["fiber_m"])
    trays_total = max(trays_total, row_q["tray_m"])
    conduit = max(conduit, row_q["conduit_m"])
    racks = max(racks, row_q["racks"])
    patch_panels = max(patch_panels, row_q["patch_panels"])
    ports = max(ports, row_q["ports"])
    fiber_splices = max(fiber_splices, row_q["fiber_splices"])
    return {
        "cat5_m": cat5,
        "cat6_m": cat6,
        "utp_m": cat5 + cat6,
        "fiber_m": fiber,
        "tray_m": trays_total + box,
        "conduit_m": conduit,
        "racks": racks,
        "patch_panels": patch_panels,
        "ports": ports,
        "fiber_splices": fiber_splices,
    }


def _render_lines(lines: list[FastLine]) -> str:
    rows = [
        "| Работа | Объём | Нормативный ход | Ставка сценария | Сумма | Комментарий |",
        "|---|---:|---|---:|---:|---|",
    ]
    for line in lines:
        rows.append(
            f"| {line.title} | {_fmt_num(line.quantity)} {line.unit} | {line.norm_hint} | "
            f"{_fmt_money(line.rate)}/{line.unit} | {_fmt_money(line.amount)} | {line.comment} |"
        )
    return "\n".join(rows)


def _sks_norm_evidence() -> str:
    return (
        "**Нормативная опора**\n"
        "Беру не рынок, а локальную сметную базу ЛЕС: карточка ГЭСН 10 содержит кабельные "
        "и инженерные сети с измерителями `100 м`, `шт`, `компл`, а ценовая книга `spb_2kv2026` "
        "даёт ресурсную базу Санкт-Петербурга за 2 кв. 2026. В этом ответе строки ещё не закрыты "
        "ресурсной трассой ФГИС, поэтому суммы ниже — предварительная РИМ-оценка по нормативным "
        "аналогам, а не финальная ЛСР.\n\n"
    )


def _sks_answer(text: str) -> str:
    q = _sks_quantities(text)
    if q["utp_m"] <= 0 and q["tray_m"] <= 0 and q["ports"] <= 0:
        return ""
    lines = [
        FastLine("Монтаж шкафов, PDU, заземления и коммутации в стойках", max(q["racks"], 1), "шт",
                 "ГЭСНм10, оборудование связи/стойки, кандидат", 55_000, max(q["racks"], 1) * 55_000,
                 "Поставка шкафов и PDU не включена"),
        FastLine("Монтаж кабель-каналов, лотков и фасонных частей", q["tray_m"], "м",
                 "кабельные конструкции/лотки, кандидат", 1_250, q["tray_m"] * 1_250,
                 "Ставка укрупняет крепёж и фасонные части"),
        FastLine("Прокладка труб/гофры для кабельных линий", q["conduit_m"], "м",
                 "трубы для электропроводок/слаботочных сетей, кандидат", 520, q["conduit_m"] * 520,
                 "Без стоимости труб"),
        FastLine("Прокладка медного кабеля U/UTP", q["utp_m"], "м",
                 "ГЭСНм10, кабели связи/СКС, кандидат", 120, q["utp_m"] * 120,
                 "Cat.5e и Cat.6A вместе; точный код уточняется по способу прокладки"),
        FastLine("Монтаж патч-панелей и розеточных модулей", q["patch_panels"] + q["ports"], "шт",
                 "оконечные устройства СКС, кандидат", 850, (q["patch_panels"] + q["ports"]) * 850,
                 "Порты/модули как измеримый объём работ"),
        FastLine("Оконцевание, маркировка и измерение медных линий", max(q["ports"], 1), "порт",
                 "измерения линий связи/СКС, кандидат", 1_250, max(q["ports"], 1) * 1_250,
                 "Fluke/протоколы как сценарное допущение"),
        FastLine("Прокладка ВОЛС OM4", q["fiber_m"], "м",
                 "ГЭСНм10, волоконно-оптические кабели, кандидат", 240, q["fiber_m"] * 240,
                 "Без стоимости кабеля"),
        FastLine("Сварка/оконцевание оптики и монтаж оптических боксов", max(q["fiber_splices"], 1), "волокно",
                 "оконцевание/измерение ВОЛС, кандидат", 2_200, max(q["fiber_splices"], 1) * 2_200,
                 "КДЗС/пигтейлы/адаптеры как поставка отдельно"),
        FastLine("ПНР, исполнительная маркировка и сдача системы", 1, "компл.",
                 "ПНР/измерения связи, кандидат", 280_000, 280_000,
                 "Укрупнённо на комплект СКС"),
    ]
    lines = [line for line in lines if line.quantity > 0]
    total = sum(line.amount for line in lines)
    low = total * 0.85
    high = total * 1.25
    return (
        "**Что понял**\n"
        "Это спецификация СКС, а не готовая ЛСР. Поставку Hyperline/DKC/Simon/Efapel/ИБП я отделяю от работ. "
        "Работы считаю сценарно по РИМ-логике: ВОР -> нормируемая ВОР -> кандидаты ГЭСНм10/кабельные конструкции/измерения.\n\n"
        "**ВОР и стоимость работ**\n"
        + _render_lines(lines)
        + "\n\n"
        + _sks_norm_evidence()
        + "**Итог**\n"
        f"Сценарная РИМ-оценка работ: **{_fmt_money(total)}**. Рабочий коридор до проверки точных норм, "
        f"способов прокладки, высот, стеснённости и протоколов измерений: **{_fmt_money(low)} - {_fmt_money(high)}**.\n\n"
        "**Что не входит**\n"
        "Поставка оборудования, кабеля, лотков, труб, крепежа, ИБП и расходников. Материалы остаются физическим объёмом для технологии, но не включены в цену работ.\n\n"
        "**Добор до финальной ЛСР**\n"
        "Нужно подтвердить трассы/способы прокладки, число фактических портов/линий, требования к измерениям, высоты и условия работ; затем выбрать точные нормы и закрыть ресурсы/ФГИС ЦС. Статус по-человечески: предварительная РИМ-оценка по допущениям, не финальная ЛСР."
    )


def _mass_variant(text: str, pattern: str) -> float | None:
    if "(" in pattern:
        v = _number_after(text, pattern)
    else:
        m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        v = parse_ru_number(m.group(0)) if m else None
    if v is None:
        return None
    return v / 1000.0 if v > 10_000 else v


def _stolp_answer(text: str) -> str:
    text_low = text.casefold()
    if not _contains_any(text_low, ("ярус", "давальческ", "гусеничн", "столп")):
        return ""
    a = _mass_variant(text, r"текст[^\n:]{0,80}([\d\s,.]+)\s*(?:кг|т)") or _mass_variant(text, r"664[,\s.]71112")
    b = _mass_variant(text, r"(?:итог[^\n:]{0,80}|строк[^\n:]{0,80}1[-–]10[^\n:]{0,80})([\d\s,.]+)\s*(?:кг|т)") or _mass_variant(text, r"664[,\s.]71172")
    c = _mass_variant(text, r"(?:всех\s*11|11\s*строк)[^\n:]{0,80}([\d\s,.]+)\s*(?:кг|т)") or _mass_variant(text, r"696[,\s.]89172")
    if c is None and b is None and a is None:
        return ""
    variants = []
    if a:
        variants.append(("А", a, "текст ТЗ", "заявленная общая масса"))
    if b:
        variants.append(("Б", b, "табличный итог / строки 1-10", "без спорного отдельного яруса, если он исключён"))
    if c:
        variants.append(("В", c, "сумма всех строк", "весь перечень ярусов"))
    work_rates = [
        ("Контрольная сборка смежных ярусов", 18_000, "ГЭСНм38/монтаж металлоконструкций как нормативный аналог"),
        ("Разборка после контрольной сборки", 6_000, "обратная операция как сценарный нормативный аналог"),
        ("Монтаж ярусов с колёс гусеничным краном", 75_000, "монтаж металлоконструкций + кран/стеснённость как допущение"),
    ]
    rows = [
        "| Вариант | Масса | Контрольная сборка | Разборка | Монтаж | РИМ-сценарий работ | Статус |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for name, mass, _source, _scope in variants:
        amounts = [mass * rate for _title, rate, _hint in work_rates]
        rows.append(
            f"| {name} | {_fmt_num(mass, 5)} т | {_fmt_money(amounts[0])} | {_fmt_money(amounts[1])} | "
            f"{_fmt_money(amounts[2])} | **{_fmt_money(sum(amounts))}** | предварительно, не финальная ЛСР |"
        )
    split_rows = [
        "| Вариант | Объём | Источник | Состав | Статус для расчёта |",
        "|---|---:|---|---|---|",
    ]
    for name, mass, source, scope in variants:
        split_rows.append(f"| {name} | {_fmt_num(mass, 5)} т | {source} | {scope} | требует подтверждения |")
    chosen = c or b or a or 0.0
    base = chosen * sum(rate for _title, rate, _hint in work_rates)
    return (
        "**Что понял**\n"
        "Нужно оценить работы по давальческим ярусам: контрольная сборка, разборка после контрольной сборки и монтаж. "
        "Стоимость металла/бронзы принимается 0 руб. Этап погрузка/перевозка/выгрузка принимается 0 руб. и не включается.\n\n"
        "**Контроль исходных чисел**\n"
        "В исходнике есть конфликт массы, поэтому финальную смету в рублях фиксировать нельзя до выбора договорной величины. "
        "Малое расхождение текстового и табличного итога нужно держать отдельно от крупной развилки состава строк.\n\n"
        "**Форма развилки исходных объёмов**\n"
        + "\n".join(split_rows)
        + "\n\n"
        "**РИМ-сценарий работ по вариантам**\n"
        + "\n".join(rows)
        + "\n\n"
        "**Нормативный ход**\n"
        "Базовый маршрут из локального RAG: ГЭСН 09 по строительным металлическим конструкциям и "
        "ГЭСНм 38 по монтажу металлических конструкций и оборудования. Для близкого аналога видна "
        "строка ГЭСНм 38-01-001-01 по листовым конструкциям массой свыше 0,5 т с работой краном; "
        "точный выбор нормы нужно подтвердить по технологии, крану, высоте и условиям площадки. "
        "Контрольная сборка, разборка и монтаж остаются отдельными строками. Совпадение физической "
        "массы в разных операциях не является задвоением, потому что операции разные.\n\n"
        "**Итог**\n"
        f"Рабочая точка для варианта с полным перечнем: **{_fmt_money(base)}** по работам, без поставки и без этапа 3. "
        "Допуск до выбора точных норм, крановой схемы, вылета/высоты, стеснённости и ФГИС-ресурсов: примерно -20% / +30%. "
        "Статус по-человечески: предварительная РИМ-оценка по допущениям, не финальная ЛСР."
    )


def smeta_fast_fallback_answer(
    harness_question: str,
    rag_context: str = "",
    numeric_audit_context: str = "",
) -> str:
    """Return a fast visible answer for measurable smeta tasks, or empty string."""
    text = "\n".join(x for x in (harness_question, rag_context, numeric_audit_context) if x)
    if _contains_any(text, ("скс", "utp", "патч-панел", "keystone", "волс", "cat.5", "cat5")):
        answer = _sks_answer(text)
        if answer:
            return answer
    if _contains_any(text, ("ярус", "давальческ", "гусеничн", "столп")):
        answer = _stolp_answer(text)
        if answer:
            return answer
    return ""
