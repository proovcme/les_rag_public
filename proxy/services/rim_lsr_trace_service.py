"""РИМ-трасса ЛСР по Приложению 3 к Методике 421/пр (форма локального сметного расчёта РИМ).

Сервис строит объяснимые строки ЛСР: работа -> ресурсы -> цены -> ОЗП/ЭМ/М ->
ФОТ -> НР/СП -> всего. Это не рендер XLSX и не новый калькулятор вместо
``lsr_assembly_service``; это методический слой evidence для проверки граф 2-12.
"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional

from proxy.smeta_core.unit_contract import norm_measure

from proxy.services import gesn_service, nr_sp_service
from proxy.services.lsr_source_coverage_service import (
    apply_confirmed_data,
    canonicalize_row_role,
    canonicalize_supply_kind,
    catalog_source_locator,
    double_count_conflicts,
    inferred_row_role,
    operation_identity,
    resolve_work_coverage,
    work_row_key,
)
from proxy.services.lsr_norm_quality_gate_service import (
    applicability_gap_kind,
    canonicalize_norm_status,
    norm_applicability_substantiated,
    qualified_norm_key,
)
from proxy.services.attachment_source_catalog_service import (
    AttachmentSourceCatalog,
    compare_model_row_to_catalog,
    source_confirms_literal_zero_quantity,
    normalize_unit,
    quantities_close,
)
from proxy.services.smeta_norm_store import reversed_action_pair


def _f(value: Any) -> float:
    try:
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def round_numeric_measure_amount(value: float) -> float:
    """Match Excel ROUND(...,2) only for the numeric-measure price trace.

    IEEE-754 finite floats need at most 309 integer decimal digits. The local
    precision also leaves room for the two cents without changing global state.
    """
    if not math.isfinite(value):
        raise ValueError("Numeric-measure amount must be finite")
    with localcontext() as context:
        context.prec = 340
        return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _round(value: Any, ndigits: int = 2) -> float:
    return round(_f(value), ndigits)


def _num(value: Any) -> Optional[float]:
    if value in (None, "", "-", "—", "–"):
        return None
    try:
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def format_ruble_amount(value: Any, *, exact: bool = False) -> str:
    """Render one money figure the way an operator has to read it.

    The readiness notice used ``:g``, so a draft on a real ВОР announced
    ``предварительная 5.91092e+06`` instead of a sum, and wrote ``8119.98`` with
    a dot (installed build 0.31.89, live case B0_camenka, 2026-09-28).  The
    grouping follows the convention already used for artifact sums
    (``smeta_artifact_service``): space between digit triples, comma before
    kopecks.  Kopecks are kept while the figure is small enough for them to
    carry information; a multi-million total stays readable instead of exact.
    ``exact`` is for a figure the operator is asked to confirm or replace —
    a rate in a price question — where rounding away the kopecks would name a
    number the document does not contain (§ 10: one set of sums).
    """
    amount = _num(value)
    if amount is None:
        return "" if value in (None, "", "-") else "—"
    if not math.isfinite(amount):
        return "—"
    decimals = 2 if exact or abs(amount) < 10_000 else 0
    return f"{amount:,.{decimals}f}".replace(",", " ").replace(".", ",")


_MARKUP_RE = re.compile(r"<[^<>]{1,60}>")


def _plain_resource_text(value: Any) -> str:
    """Strip the emphasis markup a norm card carries into a resource identity.

    A material code reached the operator as ``14.5.09.<em>11-01</em>02``
    (installed build 0.31.89, case 3 of the installed-trace check), so the
    question «нужен КАЦ: …» named a шифр no price book can contain.  Only tags
    are removed — digits, dots and dashes of the code stay exactly as the card
    has them, so nothing here can rewrite a шифр.
    """
    text = str(value or "")
    if "<" not in text:
        return text
    return " ".join(_MARKUP_RE.sub("", text).split())


def _plain_resource_line(line: dict[str, Any]) -> dict[str, Any]:
    """Return one resource with its identity fields free of card markup.

    Sanitised at the single place every resource passes through, so the flags,
    the ``price_missing:`` reason, the detail row and the adapter question all
    quote the same шифр the operator can look up (ADR-16 § 7).  Untouched when
    no tag is present, so nothing here can rewrite a code that has none.
    """
    if not any(isinstance(line.get(key), str) and "<" in str(line.get(key)) for key in ("code", "name", "unit")):
        return line
    cleaned = dict(line)
    for key in ("code", "name", "unit"):
        value = cleaned.get(key)
        if isinstance(value, str) and "<" in value:
            cleaned[key] = _plain_resource_text(value)
    return cleaned


def _norm_name(s: Any) -> str:
    import re

    return re.sub(r"\s+", " ", str(s or "").strip().lower().replace("ё", "е")).strip(" .,;:")


_NORM_REF_RE = re.compile(
    r"(ГЭСН(?:мр|м|п|р)?|ФЕР(?:мр|м|п|р)?|ТЕР(?:мр|м|п|р)?)?\s*:?\s*"
    r"(\d{2}[-–]\d{2}[-–]\d{3}[-–]\d{2})",
    flags=re.IGNORECASE,
)


def _norm_prefix(prefix: str) -> str:
    raw = str(prefix or "").strip().replace(" ", "")
    if not raw:
        return ""
    upper = raw.upper()
    for base in ("ГЭСН", "ФЕР", "ТЕР"):
        if upper.startswith(base):
            suffix = upper.replace(base, "", 1).lower()
            return base + suffix
    return raw


def _extract_norm_code(value: Any) -> str:
    """Extract a norm code from a visible LSR/BOR cell without choosing a norm."""
    match = _NORM_REF_RE.search(str(value or ""))
    if not match:
        return ""
    prefix = _norm_prefix(match.group(1) or "")
    bare = match.group(2).replace("–", "-")
    return f"{prefix}{bare}" if prefix else bare


def _canon_unit(unit: Any) -> str:
    s = str(unit or "").strip().lower().replace("³", "3").replace("²", "2")
    s = s.replace("куб.м", "м3").replace("кв.м", "м2").replace("куб м", "м3").replace("кв м", "м2")
    s = re.sub(r"\s+", "", s)
    s = s.replace("п.м.", "м").replace("п.м", "м").replace("м.п.", "м").replace("м.п", "м")
    s = re.sub(r"^\d+(?=[а-яa-z])", "", s).strip(".,;:")
    s = re.sub(r"[()]", "", s)
    aliases = {"мп": "м", "пм": "м", "meter": "м", "meters": "м", "m": "м", "m2": "м2", "m3": "м3"}
    if s in aliases:
        return aliases[s]
    if "линия" in s or "цепь" in s or s.startswith(("канал", "измерен")):
        return "линия"
    if s.startswith(("систем", "объект", "комплекс", "статив", "шкаф", "устройств", "аппарат", "точк", "порт", "мест", "номер", "отверст")):
        return "шт"
    if s.startswith(("шт", "штук", "компл", "комплект", "порт", "точк")):
        return "шт"
    if s.startswith("кг"):
        return "кг"
    if s.startswith(("тонн", "т")):
        return "т"
    if s.startswith("км"):
        return "км"
    if s.startswith("м3"):
        return "м3"
    if s.startswith("м2"):
        return "м2"
    if s == "м" or s.startswith(("м.", "мкаб", "мтруб", "мкороб", "мпровод")):
        return "м"
    return s


def _norm_unit_factor(unit: Any) -> tuple[float, str]:
    match = re.match(r"\s*(\d+(?:[.,]\d+)?)?\s*(.+)", str(unit or "").strip())
    if not match:
        return 1.0, _canon_unit(unit)
    factor = _num(match.group(1)) if match.group(1) else 1.0
    return float(factor or 1.0), _canon_unit(match.group(2))


def _same_unit_text(left: Any, right: Any) -> bool:
    a = re.sub(r"\s+", "", str(left or "").strip().lower().replace("³", "3").replace("²", "2"))
    b = re.sub(r"\s+", "", str(right or "").strip().lower().replace("³", "3").replace("²", "2"))
    return bool(a and a == b)


def _unit_conversion_factor(src: str, dst: str) -> float | None:
    if src == dst:
        return 1.0
    return {
        ("м", "км"): 0.001,
        ("км", "м"): 1000.0,
        ("кг", "т"): 0.001,
        ("т", "кг"): 1000.0,
    }.get((src, dst))


#: Price of a resource the chosen book carries in another unit.  It is a price
#: hole with its own name, not a ``needs_kac``: the book *was* checked and the
#: operator's answer is a unit, not only a number (task 2026-09-28 § 8, § 11 № 8).
BOOK_UNIT_CONFLICT_ACTION = "book_unit_conflict"


def book_price_unit_conflict(book_unit: Any, resource_unit: Any) -> str:
    """Unit the chosen book prices a шифр in, when it is not the resource's.

    An empty return means the book row is usable.  The rule has one home because
    both LSR calculators read the same book (§ 10: one document, one sum).
    The book is matched by шифр alone, so nothing in the code stopped a position
    that states «л» from being priced by a book row that says «кг» — an amount
    that would look confirmed and be arithmetically wrong
    (``stage_b/live_818/markup_price_path.json`` shows that read: the same шифр
    sent with unit «л» took the «кг» row, its unit never consulted).  No norm card
    in the sample actually disagrees with its book row: measuring the 186 matrix
    resources against the installed book gave 135 rows read by шифр, 131 of them
    naming the same unit, 0 naming another and 4 naming none
    (``stage_b/live_818/book_unit_gap.json``), and the guard moves no sum on that
    sample (``stage_b/live_819/book_unit_guard_effect.json``) — which is why
    § 11 № 8 asks for the rule, not for one repaired example.  The installed 819
    build shows both sides of the rule live
    (``stage_b/live_819/installed/book_unit_latest.json``): a position in «кг» is
    priced as before (графа 10 = 97.57), the same шифр stated in «л» prices
    nothing and names both units in the question.  Only a unit
    that reads the same after canonisation is the same price base: «п.м» and «м»,
    «шт.» and «шт» match, while «м3» and «100 м3» do not.  A differing factor
    would be a silent multiplication, and § 8 allows the code to convert only
    where it can write the formula into the trace; here the honest output is one
    question with both units named.  An empty unit on either side is deliberately
    not a conflict: a book row that names no unit says nothing about units, and a
    gap nobody can answer is not a conflict (§ 7: conflicts are shown, not
    invented).
    """

    left = str(book_unit or "").strip()
    right = str(resource_unit or "").strip()
    if not left or not right:
        return ""
    # A written zero measure is not the implicit single unit. The common norm
    # parser intentionally defaults falsy scales, so price compatibility must
    # refuse that invalid explicit base before the existing equality check.
    for unit_text in (left, right):
        explicit = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*([a-zа-яё]+[23]?)\.?",
                                unit_text.lower().replace("²", "2").replace("³", "3"))
        if explicit:
            scale = _num(explicit.group(1))
            if scale is None or not math.isfinite(scale) or scale <= 0:
                return left
    if _norm_unit_factor(left) == _norm_unit_factor(right):
        return ""
    return left


def convert_book_price_unit(
    record: Mapping[str, Any], resource_unit: Any, *, resource_code: str = "", pricebook=None,
) -> tuple[Mapping[str, Any], Optional[dict[str, Any]]]:
    """Convert strict SI pairs or compatible explicit numeric measures.

    Existing single-SI rounding stays unchanged. Numeric measures preserve the
    authoritative quoted current price before conversion and round only amounts.
    Resource quantities, model choices and the dimensionless index never change.
    """
    aliases = {
        "кг": "кг", "kg": "кг", "килограмм": "кг", "килограмма": "кг", "килограммов": "кг",
        "т": "т", "t": "т", "тонна": "т", "тонны": "т", "тонн": "т",
        "м": "м", "m": "м", "метр": "м", "метра": "м", "метров": "м",
        "км": "км", "km": "км", "километр": "км", "километра": "км", "километров": "км",
    }

    def single_unit(value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text or _norm_unit_factor(text)[0] != 1:
            return ""
        match = re.fullmatch(r"(?:1(?:[.,]0+)?\s*)?([a-zа-яё]+)\.?", text)
        return aliases.get(match.group(1), "") if match else ""

    def numeric_measure(value: Any) -> tuple[float, str] | None:
        # Full spelling only: no prefixes such as "м кабеля" or pack/density guesses.
        text = str(value or "").strip().lower().replace("²", "2").replace("³", "3")
        match = re.fullmatch(r"(?:(\d+(?:[.,]\d+)?)\s*)?([a-zа-яё]+[23]?)\.?", text)
        if not match:
            return None
        scale = _num(match.group(1)) if match.group(1) else 1.0
        base = {**aliases, "м2": "м2", "m2": "м2", "м3": "м3", "m3": "м3",
                "л": "л", "l": "л", "шт": "шт"}.get(match.group(2), "")
        if scale is None or not math.isfinite(scale) or scale <= 0 or not base:
            return None
        return float(scale), base

    book_unit = str(record.get("unit") or "").strip()
    target_unit = str(resource_unit or "").strip()
    book_measure, target_measure = numeric_measure(book_unit), numeric_measure(target_unit)
    numeric_conversion = bool(book_measure and target_measure
                              and (book_measure[0] != 1 or target_measure[0] != 1)
                              and book_price_unit_conflict(book_unit, target_unit))
    if numeric_conversion:
        book_scale, source = book_measure
        target_scale, target = target_measure
        si_factor = _unit_conversion_factor(target, source)
        factor = (target_scale / book_scale) * si_factor if si_factor is not None else None
    else:
        source, target = single_unit(book_unit), single_unit(target_unit)
        factor = _unit_conversion_factor(target, source) if source and target else None
    # Price per resource unit needs the number of book units in that unit.
    if (factor is None or not math.isfinite(factor) or factor <= 0
            or (factor == 1 and not numeric_conversion) or record.get("price_conflict")):
        return record, None
    prices = {key: _num(record.get(key)) for key in ("price_current", "price_base", "price_current_eff")}
    index = _num(record.get("index"))
    quote_field = ""
    if numeric_conversion:
        if index is not None and not math.isfinite(index):
            return record, None
        selected = prices["price_current"]
        quote_field = "price_current"
        if selected is None:
            selected = prices["price_current_eff"]
            quote_field = "price_current_eff"
        if selected is None and prices["price_base"] is not None and index is not None:
            raw_book_current = prices["price_base"] * index
            selected = round_numeric_measure_amount(raw_book_current) if math.isfinite(raw_book_current) else None
            quote_field = "round_book_base_x_index_2"
    else:
        selected = prices["price_current"]
        if selected is None and prices["price_base"] is not None and index is not None:
            selected = prices["price_base"] * index
        if selected is None:
            selected = prices["price_current_eff"]
    if selected is None or not math.isfinite(selected):
        return record, None
    converted = dict(record)
    for key, price in prices.items():
        if price is not None:
            scaled = price * factor
            if not math.isfinite(scaled) or (numeric_conversion and price != 0 and scaled == 0):
                return record, None
            converted[key] = scaled
    converted["unit"] = target_unit
    if numeric_conversion:
        resource_price = selected * factor
        if not math.isfinite(resource_price) or (selected != 0 and resource_price == 0):
            return record, None
        converted["price_current_eff"] = resource_price
    else:
        resource_price = _num(converted.get("price_current"))
        if resource_price is None and prices["price_base"] is not None and index is not None:
            resource_price = converted["price_base"] * index
        if resource_price is None:
            resource_price = _num(converted.get("price_current_eff"))
    if resource_price is None or not math.isfinite(resource_price):
        return record, None
    book_name = str(getattr(pricebook, "source_name", "") or "")
    book_sha = str(getattr(pricebook, "source_sha256", "") or "")
    source_ref = str(record.get("source_ref") or "")
    if not source_ref and (book_name or book_sha):
        source_ref = f"pricebook:{book_name}#sha256={book_sha}&code={resource_code}"
    return converted, {
        "book_unit": book_unit, "resource_unit": target_unit,
        "conversion_factor": factor,
        "formula": (
            f"{selected!r} × {factor!r} = {resource_price!r}; {book_unit} → {target_unit}"
            if numeric_conversion else
            f"price_resource_unit = price_book_unit × {factor:g}; {book_unit} → {target_unit}"
        ),
        "price_owner": "chosen_pricebook", "resource_code": resource_code,
        "book_current_price": selected, "resource_current_price": resource_price,
        "source_ref": source_ref, "book_source_name": book_name, "book_source_sha256": book_sha,
        "region": str(getattr(pricebook, "region", "") or record.get("region") or ""),
        "quarter": str(getattr(pricebook, "quarter", "") or record.get("quarter") or ""),
        **({"conversion_kind": "numeric_measure", "quote_field": quote_field,
            "book_measure_factor": book_measure[0], "resource_measure_factor": target_measure[0],
            "source_price_fields": {**prices, "index": index},
            "rounding": "authoritative_book_quote_before_conversion; amount_only_after_conversion"}
           if numeric_conversion else {}),
    }

def book_unit_conflict_note(res: dict[str, Any], book_unit: str) -> str:
    """One operator-readable line naming both sides of a rejected book price.

    The sentence has to carry the units, because that is what the operator has to
    reconcile: a book price for «кг» answers nothing about a resource the norm
    card states in «л» (§ 7 — a conflict is shown, not resolved silently).
    """

    return (
        f"цена в выбранной книге дана для «{book_unit}», а ресурс в позиции — для "
        f"«{res.get('unit') or '?'}»; цена книги не применена: "
        f"{res.get('name', '?')} ({res.get('code', '—')})"
    )


PRICE_ACTION_LABELS = {
    "needs_kac": "нужен КАЦ",
    "needs_labor_rate": "нужна ставка ОЗП",
    "needs_machinist_rate": "нужна ставка ЗПМ",
    "needs_fsem_resolution": "не согласована детализация ОТм по ФСЭМ",
    "needs_fgis_price": "нужна цена эксплуатации машины",
    "card_price_without_basis": "цена из карточки нормы, основания нет",
    "model_price_without_basis": "цена модели без подтверждённого источника",
    "model_price_unit_conflict": "цена не применена: нужен обоснованный перевод единиц",
    "kac_without_source_unit": "цена КАЦ без источника и подтверждённой единицы",
    "book_price_unit_unknown": "единица цены книги не подтверждена",
    "ambiguous_price_record": "конфликт записей выбранной книги цен",
    "unresolved_resource_group": "групповой ресурс, нужен конкретный ресурс книги",
    BOOK_UNIT_CONFLICT_ACTION: "цена книги отклонена: единицы не совпадают",
}

#: The two tokens the unowned norm-card rate is written with, shared by both LSR
#: calculators so one card cannot be «manual» money in one engine and a labelled
#: draft in the other (ADR-16 § 7).  `architecture_contract_gate` keys the pairing
#: of these two spellings; the literals inside `PriceTrace(...)` stay literal for it.
CARD_PRICE_SOURCE = "card_price"
CARD_PRICE_ACTION = "card_price_without_basis"


def price_action_label(action: Any, source: Any = "") -> str:
    """The operator's wording for one price-ladder outcome (§ 4, tracker #56).

    One home for these names: the flag the calculator raises and the column of the
    delivered check sheet must not drift into two vocabularies for one hole, and a
    file that only says «нет цены» hides which of КАЦ, ОЗП, ЗПМ or СПЭК is missing.
    """

    return PRICE_ACTION_LABELS.get(str(action or source or ""), "нужна цена")


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


_SIMPLE_COEFF_EXPR_RE = re.compile(
    r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*([*/])\s*([+-]?\d+(?:[.,]\d+)?)\s*$"
)
_SCALAR_COEFF_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
_COEFFICIENT_APPLY_ALIASES = {
    "labor": "labor",
    "ozp": "labor",
    "machine": "machine",
    "em": "machine",
    "machinist": "machine",
    "labor_and_machine": "labor_and_machine",
    "labor_machine": "labor_and_machine",
    "ozp_em": "labor_and_machine",
}


def _normalize_evidence_refs(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return []
    refs: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text:
            refs.append(text)
    return refs


def _canonical_coefficient_applies_to(value: Any) -> tuple[str | None, str]:
    if value in (None, ""):
        return None, ""
    authored = str(value).strip()
    if not authored:
        return None, ""
    key = authored.casefold().replace("-", "_").replace("+", "_").replace(" ", "_")
    while "__" in key:
        key = key.replace("__", "_")
    return _COEFFICIENT_APPLY_ALIASES.get(key), authored


def _parse_coefficient_number(value: Any) -> tuple[float | None, str]:
    """Parse a model coefficient without inventing professional meaning.

    A lone number or an unambiguous ``a * b`` / ``a / b`` of two numbers is
    numeric. Any other expression stays unparsed so calculation cannot silently
    drop it or treat a fragment as the whole value.
    """
    if value in (None, ""):
        return None, "absent"
    if isinstance(value, bool):
        return None, "unparsed"
    if isinstance(value, int | float):
        number = float(value)
        return (number, "numeric") if math.isfinite(number) else (None, "unparsed")
    text = str(value).strip()
    if not text:
        return None, "absent"
    compact = text.replace("\xa0", "").replace(" ", "")
    if _SCALAR_COEFF_RE.fullmatch(compact):
        number = float(compact.replace(",", "."))
        return (number, "numeric") if math.isfinite(number) else (None, "unparsed")
    match = _SIMPLE_COEFF_EXPR_RE.fullmatch(text)
    if match:
        left = float(match.group(1).replace(",", "."))
        right = float(match.group(3).replace(",", "."))
        if match.group(2) == "/" and right == 0:
            return None, "unparsed"
        number = left * right if match.group(2) == "*" else left / right
        return (number, "numeric") if math.isfinite(number) else (None, "unparsed")
    return None, "unparsed"


def _is_identity_coefficient(number: float | None) -> bool:
    return number is not None and abs(number - 1.0) < 1e-12


def _optional_numeric_field(row: dict[str, Any], *keys: str) -> float | None:
    raw = _first_value(row, *keys)
    number, status = _parse_coefficient_number(raw)
    return number if status == "numeric" else None


def _model_coefficient_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Carry model coefficient/evidence into a bound LSR position.

    Money is changed only when the model named the application kind explicitly.
    """
    out: dict[str, Any] = {}
    refs = _normalize_evidence_refs(_first_value(row, "evidence_refs", "source_refs"))
    if refs:
        out["evidence_refs"] = refs
    raw_coeff = row.get("coefficient")
    if raw_coeff not in (None, ""):
        out["coefficient"] = raw_coeff
    applies_token, applies_authored = _canonical_coefficient_applies_to(
        _first_value(row, "coefficient_applies_to")
    )
    if applies_authored:
        out["coefficient_applies_to"] = applies_token or applies_authored

    explicit_ozp = _optional_numeric_field(row, "k_ozp")
    explicit_em = _optional_numeric_field(row, "k_em")
    number, parse_status = _parse_coefficient_number(raw_coeff)

    if explicit_ozp is not None or explicit_em is not None:
        out["coefficient_application"] = "applied"
        out["k_ozp"] = 1.0 if explicit_ozp is None else explicit_ozp
        out["k_em"] = 1.0 if explicit_em is None else explicit_em
        if number is not None:
            out["coefficient_value"] = number
        if refs:
            out["coefficient_basis"] = ", ".join(refs)
        return out

    if applies_authored and applies_token is None:
        out["coefficient_application"] = "unrecognized"
        return out
    if parse_status == "unparsed":
        out["coefficient_application"] = "unparsed"
        return out
    if number is None or _is_identity_coefficient(number):
        if applies_token and number is None:
            out["coefficient_application"] = "missing"
        return out

    out["coefficient_value"] = number
    if applies_token is None:
        out["coefficient_application"] = "missing"
        return out

    out["coefficient_application"] = "applied"
    out["coefficient_applies_to"] = applies_token
    if applies_token == "labor":
        out["k_ozp"] = number
        out["k_em"] = 1.0
    elif applies_token == "machine":
        out["k_ozp"] = 1.0
        out["k_em"] = number
    else:
        out["k_ozp"] = number
        out["k_em"] = number
    if refs:
        out["coefficient_basis"] = ", ".join(refs)
    return out


def _resolve_position_coefficients(
    position: dict[str, Any],
    *,
    k_ozp: float,
    k_em: float,
    coefficient_basis: str,
) -> tuple[float, float, str, dict[str, Any]]:
    resolved_ozp = k_ozp
    resolved_em = k_em
    if "k_ozp" in position and position.get("k_ozp") not in (None, ""):
        resolved_ozp = _f(position.get("k_ozp"))
    if "k_em" in position and position.get("k_em") not in (None, ""):
        resolved_em = _f(position.get("k_em"))
    refs = _normalize_evidence_refs(position.get("evidence_refs"))
    basis = str(position.get("coefficient_basis") or coefficient_basis or "").strip()
    if not basis and refs:
        basis = ", ".join(refs)
    return resolved_ozp, resolved_em, basis, {
        "application": str(position.get("coefficient_application") or ""),
        "authored": position.get("coefficient"),
        "applies_to": position.get("coefficient_applies_to"),
        "refs": refs,
    }


def _cited_conversion(row: Mapping[str, Any], source_qty: float) -> tuple[float, dict[str, Any]] | None:
    """Use an authored derived quantity only with an explicit calculation basis."""

    source = str(
        row.get("conversion_source")
        or row.get("quantity_source")
        or ""
    ).strip()
    if not source:
        return None
    # Use the same numeric literal parser as the validation step. A text reader
    # that strips letters would turn an accepted "1e3" into 13 here.
    calc = _num(row.get("calc_quantity"))
    factor = _num(row.get("conversion_factor"))
    if calc is not None and math.isfinite(calc):
        return float(calc), {
            "status": "cited_calc_quantity",
            "conversion_source": source,
            "calc_quantity": float(calc),
            **({"conversion_factor": float(factor)} if factor is not None and math.isfinite(factor) else {}),
        }
    if factor is None or not math.isfinite(factor):
        return None
    return round(float(source_qty) * float(factor), 9), {
        "status": "cited_conversion_factor",
        "conversion_source": source,
        "conversion_factor": float(factor),
    }


@dataclass(frozen=True)
class PriceTrace:
    price: Optional[float]
    source: str
    column_8: Optional[float] = None
    column_9: Optional[float] = None
    column_10: Optional[float] = None
    basis: str = ""
    action: str = ""
    #: Unit the chosen book states for this шифр, filled only when the book row
    #: was rejected for naming another unit.  The row's own unit is column 4, so
    #: an operator reading the question sees both sides of the conflict.
    book_unit: str = ""
    #: Concrete resources of the price-book group this row names, filled only for
    #: ``unresolved_resource_group`` (task 2026-09-29 § 3).  It is a listing, never
    #: a choice: the first price of a group is not the group's price.
    group: Optional[Mapping[str, Any]] = None
    record_conflict: Optional[Mapping[str, Any]] = None
    unit_conversion: Optional[Mapping[str, Any]] = None


#: A norm resource that names a price-book group rather than one member of it.
#: The book has money for the family and no money for the position, so the hole is
#: "which resource", not "how much" — and reporting it as ``needs_price`` would ask
#: the operator for a number they cannot legitimately give (task 2026-09-29 § 3).
RESOURCE_GROUP_ACTION = "unresolved_resource_group"

#: Task 2026-09-29 § 4: an open position answers one of two different questions, and
#: the calculator's own reason tags say which.  «price_missing:…» and
#: «card_price_without_basis:…» are money — the structure is built and only the price
#: (or its owner) is missing.  Any other tag is the structure itself; «action_conflict:»
#: is neither, it is the double-counting question the operator has to settle.  One
#: place splits them, so the check sheet, the readiness count and the sum agree.
PRICE_REASON_PREFIXES = (
    "ambiguous_price_record:",
    "price_missing:", "card_price_without_basis:", "model_price_without_basis:", "kac_without_source_unit:",
    "position_price_without_basis:", "book_price_unit_unknown:",
    "position_price_kind_unknown:", "position_price_unit_conflict:",
    "model_price_unit_conflict:",
    "supply_price_kind_conflict",
)
CONFLICT_REASON_PREFIXES = ("action_conflict:",)

#: The operator-confirmed-price note explains *how* a finished position got its money;
#: it is not a hole in the calculation.  Counting it as a gap flag made a document whose
#: every operation is fully priced read ``priced_partial`` in one consumer while the
#: projection of the same rows answered «позиция полностью рассчитана=да» in another
#: (§ 4 / § 10 — one meaning in every consumer).  The note stays in ``flags`` so every
#: surface can still print it; only the status decision treats it as informational.
OPERATOR_PRICE_NOTE_PREFIX = "итог позиции взят по подтверждённой цене оператора"
SOURCE_PRICE_NOTE_PREFIX = "итог позиции взят по подтверждённой цене источника"


def is_informational_flag(flag: Any) -> bool:
    """Does this calculator flag describe how the money was taken, not what is open?"""

    return str(flag or "").startswith((OPERATOR_PRICE_NOTE_PREFIX, SOURCE_PRICE_NOTE_PREFIX))


def gap_flags(flags: Any) -> list[Any]:
    """The part of a flag list that says something is still missing."""

    return [flag for flag in (flags or []) if not is_informational_flag(flag)]


def is_price_reason(reason: Any) -> bool:
    return str(reason or "").startswith(PRICE_REASON_PREFIXES)


def is_conflict_reason(reason: Any) -> bool:
    return str(reason or "").startswith(CONFLICT_REASON_PREFIXES)


#: The seven questions task 2026-09-29 § 4 names for one operation, in the order both
#: consumers print them.  ``volume_verified`` travels beside them because Directive 2.2
#: treats the volume as its own independent question; it is listed after the seven so a
#: reader can tell the contract apart from the extra check.
OPERATION_READINESS_FIELDS = (
    "source_accounted",
    "operation_defined",
    "norm_selected",
    "applicability_substantiated",
    "structure_calculated",
    "known_amount_present",
    "position_calculated",
    "volume_verified",
)


#: Each of the seven questions, worded once for the operator, with what its open
#: state means.  The «Проверка» sheet, the remarks block of the delivered file and the
#: readiness card all read these words, so one question is phrased one way in the whole
#: document (§ 4 / § 10).
OPERATION_QUESTIONS = (
    ("source_accounted", "источник учтён", "строка исходного ВОР не дошла до ревизии"),
    ("operation_defined", "работа определена",
     "роль строки не объявлена: это работа, материал, машина или заголовок"),
    ("norm_selected", "шифр выбран", "позиция стоит без выбранной нормы"),
    ("applicability_substantiated", "применимость обоснована",
     "шифр назван, но приведённая карточка нормы его не подтверждает"),
    ("structure_calculated", "расчёт структуры построен",
     "состав позиции не собран: ресурсы, единицы или начисления не закрыты"),
    ("known_amount_present", "известная стоимость есть",
     "в позиции нет ни одного посчитанного рубля"),
    ("position_calculated", "позиция полностью рассчитана",
     "итог позиции не сведён, расчёт открыт"),
    # Directive 2.2 keeps the volume as its own question beside § 4's seven, so the
    # sheet and the remarks block state it too instead of folding it into the money.
    ("volume_verified", "объём проверен",
     "количество или единица строки не сверены с исходником"),
)


def row_projection(binding: Mapping[str, Any]) -> dict[str, Any]:
    """The one revision projection of one row: identity, role, decision, seven answers.

    The «Проверка» sheet and the readiness card read this, and nothing else, so the
    same operation cannot be «шифр выбран=да» in the file and unselected in the chat
    (§ 10).
    Identity comes from the stable operation ids the revision already carries; no
    field is invented here — every value is what the row's own readiness said.
    """

    readiness = binding.get("readiness")
    readiness = readiness if isinstance(readiness, Mapping) else {}
    position = binding.get("position")
    position = position if isinstance(position, Mapping) else {}
    source_row = binding.get("source_row")
    source_row = source_row if isinstance(source_row, Mapping) else {}
    return {
        "locator": str(binding.get("row") or ""),
        "work_id": str(binding.get("work_id") or position.get("work_id") or ""),
        "operation_id": str(position.get("op_key") or operation_identity(source_row)),
        # § 4: the number the position carries in the delivered document, how many
        # operations the revision built on this one source row, and which operation a
        # supply line belongs to — the link an operator needs to find the row in the
        # file and to see that one line is not one position.
        "position_no": binding.get("position_no"),
        "locator_operations": int(binding.get("locator_operations") or 1),
        "parent_locator": str(
            position.get("work_row")
            or source_row.get("work_row")
            or binding.get("work_row")
            or ""
        ),
        "covered_by_work_id": str(binding.get("covered_by_work_id") or ""),
        "covered_by_operation_id": str(binding.get("covered_by_operation_id") or ""),
        "row_role": str(
            binding.get("row_role") or readiness.get("row_role") or ""
        ),
        "status": str(binding.get("status") or ""),
        "norm_code": str(binding.get("code") or ""),
        "norm_status": str(binding.get("norm_status") or ""),
        **{name: readiness.get(name) for name in OPERATION_READINESS_FIELDS},
        **({"charge_not_required": True} if binding.get("charge_not_required") is True else {}),
        "prices_provided": readiness.get("prices_provided"),
        "open_reasons": list(readiness.get("open_reasons") or []),
        # § 4: how the operator's own money became the position's sum, in the
        # calculator's words.  Flags never reach the delivered file, so without this
        # field an operator who answered «100 рублей за единицу» cannot see in the
        # ЛСР which unit that price was multiplied by.
        "price_note": str(binding.get("price_note") or ""),
        "binding_message": str(binding.get("message") or ""),
        **({"normative_generation_reason": str(binding["normative_generation_reason"])}
           if binding.get("normative_generation_reason") else {}),
    }


def operation_open_questions(
    projection: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(blockers, warnings) for the delivered file, read off the rows' own answers.

    Task 2026-09-29 § 4 (tracker #54, #60): the «Общие замечания и незакрытые позиции»
    block had no producer at all, so a revision with open rows printed an empty section
    while the open questions sat in the same rows.  Nothing is judged here — each line
    names one locator, the question that row left unanswered and the reason the
    calculator gave.  A heading keeps ``н/п`` answers and therefore produces no remark
    (§ 4: its absent applicability is not a defect).
    """

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    closed_statuses = {"bound", "covered", "resource_linked", "structure_accounted"}
    for item in projection:
        locator = str(item.get("locator") or "") or "?"
        work_id = str(item.get("work_id") or "")
        status = str(item.get("status") or "")
        # § 4: a remark has to be findable in the document.  The locator names the
        # source line, the position number names the line of the delivered ЛСР, and a
        # supply line states the operation it belongs to — an operator reading
        # «строка А!R37» without that link cannot tell which of two positions on the
        # same source row is meant.
        where = f"Строка {locator}"
        position_no = item.get("position_no")
        if isinstance(position_no, int) and position_no > 0:
            where += f" (позиция {position_no})"
        siblings = int(item.get("locator_operations") or 1)
        if siblings > 1:
            where += f", на этой строке {siblings} операции"
        parent = str(item.get("parent_locator") or "")
        if parent and parent != locator:
            where += f", относится к {parent}"
        reasons = [str(value) for value in (item.get("open_reasons") or [])]
        money = [value for value in reasons if is_price_reason(value)]
        conflicts = [value for value in reasons if is_conflict_reason(value)]
        structural = [
            value for value in reasons
            if not is_price_reason(value) and not is_conflict_reason(value)
        ]
        if status and status not in closed_statuses:
            blockers.append(
                {
                    "code": locator,
                    "work_id": work_id,
                    "field": "status",
                    "reason": (
                        f"{where}: {item.get('binding_message') or status} — "
                        "решение по ней не принято, в расчёт она не входит."
                    ),
                }
            )
            continue
        for name, label, meaning in OPERATION_QUESTIONS:
            if item.get(name) is not False:
                continue
            # § 4: an open question names what to do next.  When the only reasons
            # the calculator left are about money, saying «расчёт открыт» would send
            # the operator to recalculate a position whose structure is already
            # built, so that row says the price is what keeps the sum open.
            detail = meaning
            if name in {"position_calculated", "known_amount_present"}:
                if money and not structural:
                    detail = (
                        f"структура собрана, не хватает цены ({', '.join(money[:3])})"
                    )
                elif conflicts:
                    detail = (
                        f"сумма открыта из-за двойного учёта ({', '.join(conflicts[:2])})"
                    )
            blockers.append(
                {
                    "code": locator,
                    "work_id": work_id,
                    "field": name,
                    "reason": f"{where}: {label} — нет ({detail}).",
                }
            )
        for reason in conflicts:
            blockers.append(
                {
                    "code": locator,
                    "work_id": work_id,
                    "field": "double_count",
                    "reason": (
                        f"{where}: строка сама называет другую операцию, чем "
                        f"выбранный шифр ({reason}) — нужен ответ оператора."
                    ),
                }
            )
        if str(item.get("prices_provided") or "") == "не по базе":
            warnings.append(
                {
                    "code": locator,
                    "work_id": work_id,
                    "field": "price_from_norm_card",
                    "reason": (
                        f"{where}: цена взята из карточки нормы, а не из "
                        "выбранной ценовой книги или КАЦ — сумма позиции черновая."
                    ),
                }
            )
        # § 4: the file states the arithmetic the operator's answer produced, including
        # the unit it was multiplied by.  This is the calculator's own note, copied,
        # never recomputed here — a position measured in «100 м2» against a source line
        # in «м2» is the one place where a flat price can be off by that factor, and an
        # operator has to be able to see and correct it in the delivered document.
        price_note = str(item.get("price_note") or "")
        if price_note:
            warnings.append(
                {
                    "code": locator,
                    "work_id": work_id,
                    "field": "operator_price_unit",
                    "reason": f"{where}: {price_note}.",
                }
            )
        if money:
            warnings.append(
                {
                    "code": locator,
                    "work_id": work_id,
                    "field": "price_gaps",
                    "reason": (
                        f"{where}: нет цен у {len(money)} ресурса(ов) — "
                        f"{', '.join(money[:6])}."
                    ),
                }
            )
    return blockers, warnings



def resource_group_state(res: Any, pricebook: Any) -> dict[str, Any]:
    """Group state of one resource row, or ``{}`` when there is nothing to choose.

    One home for the rule, because both LSR calculators read the same book and a
    document may not get two sums (§ 10): the assembly engine and the РИМ trace both
    ask this function and both stop on the same row.  A book that does not implement
    ``resource_group`` (a stub in a test, an older cached object) reports no group
    rather than a fabricated one, so the row keeps its previous ``needs_price`` hole.
    """

    if pricebook is None or not isinstance(res, Mapping):
        return {}
    code = str(res.get("code") or "").strip()
    if not code:
        return {}
    resolver = getattr(pricebook, "resource_group", None)
    if not callable(resolver):
        return {}
    try:
        state = resolver(code)
    except (TypeError, ValueError):
        return {}
    if not isinstance(state, Mapping):
        return {}
    if str(state.get("state") or "") != RESOURCE_GROUP_ACTION:
        return {}
    return dict(state)


def resource_group_note(res: Any, state: Mapping[str, Any]) -> str:
    """One operator-readable line: the family is priced, the member is not chosen."""

    code = str((state or {}).get("group") or "").strip() or "?"
    total = int((state or {}).get("total") or 0)
    unit = str(res.get("unit") or "").strip() or "без единицы"
    return (
        f"групповой ресурс {code}: книга цен даёт {total} конкретных ресурсов этой группы, "
        f"позиция в «{unit}» требует выбрать один; первая цена группы не берётся"
    )


def _missing_price_action(res: dict[str, Any]) -> str:
    kind = str(res.get("kind") or "")
    if kind == "material":
        return "needs_kac"
    if kind == "labor":
        return "needs_labor_rate"
    if kind == "machinist":
        return "needs_machinist_rate"
    if kind == "machine":
        return "needs_fgis_price"
    return "needs_price"


def price_is_attributed(res: dict[str, Any]) -> bool:
    """Whether an explicit resource price has an owner the customer can check.

    Only two owners exist: the operator who confirmed the price, and a source
    reference written with it.  A number the imported norm card carries by
    itself belongs to neither (ADR-16 § 7).

    Both LSR calculators ask this one question, so a norm-card rate cannot be
    counted as operator money by one engine and as an unowned draft by the
    other (§ 10: one document, one amount).
    """

    if res.get("price_confirmed"):
        return True
    return bool(str(res.get("price_source_ref") or "").strip())


def _visible_row_has_evidence(row: Mapping[str, Any]) -> bool:
    refs = _normalize_evidence_refs(_first_value(row, "evidence_refs", "source_refs"))
    refs = [ref for ref in refs if ref.casefold() not in {"-", "—", "–", "missing", "n/a", "нет", "none", "null"}]
    if not refs:
        return False
    if "evidence_bindings" not in row:
        # Direct operator/editor rows retain their explicit source-reference
        # contract. The active model adapter always supplies immutable bindings.
        return True
    bindings = row.get("evidence_bindings")
    if not isinstance(bindings, Mapping):
        return False
    known = {str(alias).strip().casefold(): str(identity or "").strip() for alias, identity in bindings.items()}
    return all(bool(known.get(ref.casefold())) for ref in refs)


def _visible_price_owner(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return existing confirmation/source ownership; never invent an operator.

    The workbook's confirmed-data overlay supplies ``confirmed_by`` outside the
    model result. A model-written token ``price_source=operator`` is a claim,
    not that confirmation. A commercial source needs its explicit reference.
    """
    from proxy.services.lsr_source_coverage_service import is_operator_confirmed_field

    source = str(row.get("price_source") or "").strip()
    if is_operator_confirmed_field(row, "confirmed_price"):
        return source or "operator", "operator"
    if "_price_evidence_check" in row:
        check = row["_price_evidence_check"]
        if not isinstance(check, Mapping) or any(check.get(key) is not True for key in (
            "price_in_refs", "unit_in_refs", "source_in_refs", "optional_context_in_refs",
        )):
            return "", ""
    if source and source.casefold() not in {
        "operator", "оператор", "manual", "model", "-", "—", "–", "missing", "n/a", "нет", "none", "null",
    } and _visible_row_has_evidence(row):
        return source, "source"
    return "", ""


def _resolve_price_trace(
    res: dict[str, Any],
    *,
    pricebook=None,
    kac_map: dict[str, float] | None = None,
) -> PriceTrace:
    """Вернуть цену ресурса с сохранением происхождения граф 8-10."""
    explicit = (
        _round(res.get("price")) if res.get("price") not in (None, "") else None
    )
    explicit_unit_conflict = (
        book_price_unit_conflict(res.get("price_unit"), res.get("unit"))
        if res.get("price_origin") == "model_result" else ""
    )
    if explicit is not None and price_is_attributed(res) and not explicit_unit_conflict:
        if isinstance(res.get("resource_binding"), Mapping) and res["resource_binding"].get("action") == "reuse":
            return PriceTrace(price=explicit, source="reuse", column_10=explicit,
                              basis=str(res.get("price_source_ref") or ""), action="reuse")
        return PriceTrace(price=explicit, source="manual", column_10=explicit, basis="explicit_resource_price")

    code = str(res.get("code") or "").strip()
    book_unit_conflict = ""
    if code and pricebook is not None:
        rec = pricebook.lookup(code)
        if rec is not None and rec.get("price_conflict"):
            return PriceTrace(price=None, source="ambiguous_price_record", basis="chosen_pricebook",
                              action="ambiguous_price_record", record_conflict=rec["price_conflict"])
        if rec is not None:
            # The шифр is in the chosen book; its price may still be for another
            # unit, and reading the number anyway would hand the position a
            # confirmed amount that no arithmetic supports (§ 11 № 8).
            rec, unit_conversion = convert_book_price_unit(
                rec, res.get("unit"), resource_code=code, pricebook=pricebook,
            )
            book_unit_conflict = book_price_unit_conflict(rec.get("unit"), res.get("unit"))
        if rec is not None and not book_unit_conflict:
            if unit_conversion and unit_conversion.get("conversion_kind") == "numeric_measure":
                # A quoted current book price is already rounded in its own
                # measure. Never promote base×index precision past that quote.
                quote_field = unit_conversion["quote_field"]
                source, basis = {
                    "price_current": ("fgis_current", "split_form_col_8"),
                    "price_current_eff": ("fgis_effective", "split_form_effective_price"),
                    "round_book_base_x_index_2": ("fgis_base_index", "split_form_col_5_x_col_9"),
                }[quote_field]
                return PriceTrace(
                    price=unit_conversion["resource_current_price"], source=source, basis=basis,
                    column_8=_num(rec.get("price_base")), column_9=_num(rec.get("index")),
                    column_10=unit_conversion["resource_current_price"],
                    unit_conversion=unit_conversion,
                )
            unit_action = (
                "book_price_unit_unknown"
                if res.get("requires_price_unit_provenance") and (
                    not str(rec.get("unit") or "").strip() or not str(res.get("unit") or "").strip()
                ) else ""
            )
            current = _num(rec.get("price_current"))
            if current is not None:
                price = _round(current)
                return PriceTrace(
                    price=price,
                    source="fgis_current",
                    column_10=price,
                    basis="split_form_col_8",
                    action=unit_action,
                    unit_conversion=unit_conversion,
                )
            base = _num(rec.get("price_base"))
            index = _num(rec.get("index"))
            if base is not None and index is not None:
                price = _round(base * index)
                return PriceTrace(
                    price=price,
                    source="fgis_base_index",
                    column_8=_round(base),
                    column_9=_round(index, 6),
                    column_10=price,
                    basis="split_form_col_5_x_col_9",
                    action=unit_action,
                    unit_conversion=unit_conversion,
                )
            eff = _num(rec.get("price_current_eff"))
            if eff is not None:
                price = _round(eff)
                return PriceTrace(
                    price=price,
                    source="fgis_effective",
                    column_10=price,
                    basis="split_form_effective_price",
                    action=unit_action,
                    unit_conversion=unit_conversion,
                )

    if str(res.get("kind")) == "material" and kac_map:
        price = kac_map.get(_norm_name(res.get("name")))
        if price is not None:
            price = _round(price)
            return PriceTrace(
                price=price,
                source="kac",
                column_10=price,
                basis="kac",
                # The legacy map only carries a name and number. On a model
                # supply row it cannot establish the quote's source or unit.
                action="kac_without_source_unit" if res.get("requires_kac_provenance") else "",
                book_unit=book_unit_conflict,
            )

    # Last resort, and never a silent one: the number written inside the norm
    # card is applied only when neither the chosen book nor КАЦ has the resource,
    # it is labelled with its own action, and the position stops being a
    # confirmed amount (ADR-16 § 7, acceptance § 12 "no invented prices").
    if explicit is not None and res.get("price_origin") == "model_result":
        if explicit_unit_conflict:
            return PriceTrace(
                price=None, source="model_price_unit_conflict", basis="model_authored_price",
                action="model_price_unit_conflict",
            )
        return PriceTrace(
            price=explicit, source="model_unattributed_price", column_10=explicit,
            basis="model_authored_price", action="model_price_without_basis", book_unit=book_unit_conflict,
        )
    if explicit is not None:
        return PriceTrace(
            price=explicit,
            source="card_price",
            column_10=explicit,
            basis="norm_card_price",
            action="card_price_without_basis",
            book_unit=book_unit_conflict,
        )

    if book_unit_conflict:
        # Nothing else owns a number for this resource.  The hole is named after
        # its real cause: the operator's answer is a unit, not only a price, and
        # "needs КАЦ" would make them look for a price they already have.
        return PriceTrace(
            price=None,
            source=BOOK_UNIT_CONFLICT_ACTION,
            basis=BOOK_UNIT_CONFLICT_ACTION,
            action=BOOK_UNIT_CONFLICT_ACTION,
            book_unit=book_unit_conflict,
        )

    group = resource_group_state(res, pricebook)
    if group:
        # The chosen book prices this family and the position names no member of it.
        # The honest hole is "which resource", not "how much": a price asked here would
        # be answered with whichever row the book happens to list first (§ 3).  The
        # concrete resources travel with the question so the answer is a choice.
        return PriceTrace(
            price=None,
            source=RESOURCE_GROUP_ACTION,
            basis=RESOURCE_GROUP_ACTION,
            action=RESOURCE_GROUP_ACTION,
            book_unit=book_unit_conflict,
            group=group,
        )

    action = _missing_price_action(res)
    return PriceTrace(price=None, source=action, basis=action, action=action)


def _position_resources(position: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Вернуть норму и ресурсы с ``per_unit``; explicit resources поддержаны для тестов/ручного ввода."""
    code = str(position.get("code") or "").strip()
    # A visible row's quantity/unit conversion and resource actions used this
    # app-owned snapshot. A later lookup must not mix another generation into
    # the same calculation, even if the source was replaced at the same path.
    snapshot = position.get("_norm_snapshot")
    norm = deepcopy(snapshot) if isinstance(snapshot, Mapping) else (
        gesn_service.get_norm(code) if code else None
    )
    # ``resources`` is a tri-state contract:
    # - key absent: hydrate the norm's source resources;
    # - non-empty list: use the explicit model revision;
    # - empty list: the revision intentionally contains no confirmed resources.
    # Treating [] as "not supplied" resurrected the raw norm after an unresolved
    # model review and bypassed labor normalization.
    if code and "resources" not in position:
        if norm is None:
            return None, []
        from proxy.smeta_core.resource_normalizer import normalize_norm_resources

        return norm, [
            _plain_resource_line(dict(res))
            for res in normalize_norm_resources(list(norm.get("resources") or []))
        ]

    work_qty = gesn_service._optional_quantity(position.get("qty"))
    resources: list[dict[str, Any]] = []
    for res in position.get("resources") or []:
        line = _plain_resource_line(dict(res))
        if line.get("per_unit") in (None, ""):
            supplied_qty = gesn_service._optional_quantity(line.get("qty"))
            line["per_unit"] = (
                gesn_service._optional_quantity(supplied_qty / work_qty)
                if supplied_qty is not None and work_qty not in (None, 0) else None
            )
        resources.append(line)
    return norm, resources


def _row(
    row_type: str,
    label: str,
    *,
    columns: dict[int, Any] | None = None,
    source: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": row_type,
        "label": label,
        "columns": {str(k): v for k, v in (columns or {}).items() if v not in (None, "")},
        "source": source,
        "meta": meta or {},
    }


def _resource_coeff(kind: str, *, k_ozp: float, k_em: float) -> float:
    if kind == "labor":
        return k_ozp
    if kind in {"machine", "machinist"}:
        return k_em
    return 1.0


def _has_uncomputed_norm_components(item: Mapping[str, Any]) -> bool:
    """Recognize only the explicitly authored field, never coverage prose."""
    value = item.get("norm_components")
    return not (value is None or value == "" or (isinstance(value, list) and not value))


def _norm_components_audit_warnings(position: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Preserve the complete unsupported value in bounded literal audit cells."""
    if not _has_uncomputed_norm_components(position):
        return []
    # ASCII JSON also bounds Excel's UTF-16 units for astral source characters.
    literal = json.dumps(position["norm_components"], ensure_ascii=True, separators=(",", ":"))
    pieces = [literal[offset:offset + 30000] for offset in range(0, len(literal), 30000)]
    source_row = str(position.get("source_row") or "")
    operation_id = str(position.get("op_key") or position.get("work_id") or "")
    return [{
        "code": "norm_components_not_calculated", "source_row": source_row,
        "work_id": operation_id, "fragment": index + 1, "fragments": len(pieces),
        "reason": (
            f"Строка {source_row}, операция {operation_id}: norm_components сохранён, но не рассчитан. "
            f"Фрагмент {index + 1}/{len(pieces)}. JSON: " + piece
        ),
    } for index, piece in enumerate(pieces)]


def build_position_trace(
    position: dict[str, Any],
    *,
    pricebook=None,
    kac_map: dict[str, float] | None = None,
    k_ozp: float = 1.0,
    k_em: float = 1.0,
    coefficient_basis: str = "",
) -> dict[str, Any]:
    """Построить доказательную РИМ-трассу одной позиции ЛСР.

    ``position`` обычно содержит ``code`` ГЭСН и ``qty`` объёма работ. Если ``resources`` не переданы,
    ресурсы берутся из ``gesn_service``. НР/СП берутся из позиции, из нормы или из ``nr_sp_service``.
    """
    kac_lookup = {_norm_name(k): _f(v) for k, v in (kac_map or {}).items()}
    work_qty = _f(position.get("qty")) or 0.0
    k_ozp, k_em, coefficient_basis, coeff_meta = _resolve_position_coefficients(
        position,
        k_ozp=k_ozp,
        k_em=k_em,
        coefficient_basis=coefficient_basis,
    )
    norm, resources = _position_resources(position)
    resource_binding_conflicts = list(position.get("resource_binding_conflicts") or [])
    if position.get("exclude_gesn_materials") and any(item.get("kind") == "material" for item in resources):
        # A legacy marker does not identify an authored target. Preserve the
        # composition and expose its unresolved supply relationship instead.
        resource_binding_conflicts.append({
            "code": "separate_supply_possible_overlap",
            "reason": "legacy separate-supply marker has no explicit resource target",
            "norm_material_resources": [dict(item) for item in resources if item.get("kind") == "material"],
        })
    from proxy.services import fsem_machinist_service as fsem
    from proxy.services import gesn_fgis_service as gfgis

    if pricebook is not None:
        resources, fsem_trace = fsem.enrich_machinists(resources, quantity_field="per_unit")
    else:
        # A raw trace without a pricebook preserves explicit legacy/manual
        # machinist prices. Full FSEM replacement is meaningful only together
        # with the active tariff book that prices the derived driver codes.
        resources = [dict(item) for item in resources]
        fsem_trace = {
            "schema": "fsem_enrichment_v1",
            "status": "not_applied_without_pricebook",
        }
    # § 3: the calculator reports the labour шифры whose origin the imported card does not
    # state itself; it never invents one while pricing.  The derivation belongs to the norm
    # readers (and to the ФГИС ingest), and both engines show the same provenance (§ 10).
    labor_code_trace = gfgis.labor_code_provenance(resources)
    flags: list[str] = []
    completeness_reasons: list[str] = []
    uncomputed_components = _has_uncomputed_norm_components(position)
    if uncomputed_components:
        flags.append("Состав норм norm_components сохранён, но не рассчитан; "
                     "дополнительные начисления требуют отдельных операций и обоснованных расчётных объёмов")
        completeness_reasons.append("norm_components_not_calculated")
    if position.get("norm_card_body_unread"):
        flags.append("Полная карточка выбранной нормы не была прочитана моделью")
        completeness_reasons.append("norm_card_body_unread")
    from proxy.services.model_resource_binding_service import resource_binding_conflict_note

    for conflict in resource_binding_conflicts:
        prefix = "" if conflict.get("code") in {"separate_supply_possible_overlap", "separate_supply_review_conflict"} else "Конфликт действия над ресурсом: "
        flags.append(prefix + resource_binding_conflict_note(conflict))
        completeness_reasons.append(str(conflict.get("code") or "resource_binding_conflict"))
    if position.get("resource_selection_unsubstantiated"):
        flags.append("соответствие выбранного ресурса строке не подтверждено ссылкой на источник")
        completeness_reasons.append("resource_selection_unsubstantiated")
    if position.get("supply_resource_match_unsubstantiated"):
        flags.append("Соответствие выбранного ресурса исходному изделию не подтверждено моделью; "
                     "найденная цена сама по себе этого не доказывает")
        completeness_reasons.append("supply_resource_match_unsubstantiated")
    if position.get("supply_price_kind_conflict"):
        flags.append("цена поставки требует уточнения: для материала или оборудования допустима только цена за единицу")
        completeness_reasons.append("supply_price_kind_conflict")
    if fsem_trace.get("status") == "unresolved":
        details = list(fsem_trace.get("reasons") or fsem_trace.get("missing_machine_codes") or [])
        flags.append("ФСЭМ не смог детализировать ОТм: " + "; ".join(str(item) for item in details))
        completeness_reasons.append("fsem_unresolved")
    elif fsem_trace.get("status") == "derived_with_aggregate_discrepancy":
        flags.append(
            "ОТм рассчитана отдельно по каждой машине и экипажу ФСЭМ;"
            f" опубликованный агрегат {fsem_trace['source_machinist_hours']:g}"
            f" не совпадает с расчётными часами {fsem_trace['derived_machinist_hours']:g}."
            " Нормативные источники требуют сверки; сумма остаётся предварительной."
        )
        completeness_reasons.append("fsem_aggregate_discrepancy")
    norm_source_integrity: dict[str, Any] = {}
    if norm and str(norm.get("_source_kind") or "") == "structured_sqlite":
        from proxy.smeta_core.integrity import normative_base_integrity

        norm_source_integrity = normative_base_integrity(base_path=str(norm.get("_source_path") or ""))
        if not norm_source_integrity.get("trusted_for_pricing"):
            flags.append("нормативная база в карантине: semantic integrity gate не пройден")
            completeness_reasons.append("normative_source_untrusted")
    if norm and str(norm.get("_source_kind") or "") == gesn_service.SEED_SOURCE_KIND:
        # § 3: the demo seed is reachable only when a scenario named it explicitly, and
        # even then the position must not read as base-backed money.
        flags.append("норма взята из демо-семени (LES_GESN_SEED_ENABLED/path), не из базы")
        completeness_reasons.append("normative_source_demo_seed")
        norm_source_integrity = {
            "trusted_for_pricing": False,
            "source_kind": gesn_service.SEED_SOURCE_KIND,
            "base_path": str(norm.get("_source_path") or ""),
        }
    if position.get("code") and norm is None and not position.get("resources"):
        flags.append(
            f"норма ГЭСН не найдена в базе: {position.get('code')} "
            "— карточку не подменяем, расчёт позиции не закрыт"
        )
        completeness_reasons.append("norm_missing")
    action_conflict = position.get("action_conflict")
    if isinstance(action_conflict, Mapping) and action_conflict:
        # Task § 11 №8: the amount is still shown, but a position whose own row
        # names the opposite operation is a draft until the conflict is resolved.
        flags.append(f"противоречие операции: {action_conflict.get('message') or ''}".strip())
        completeness_reasons.append(
            "action_conflict:"
            f"{action_conflict.get('row_action') or ''}->{action_conflict.get('norm_action') or ''}"
        )
    application = str(coeff_meta.get("application") or "")
    authored_coeff = coeff_meta.get("authored")
    if application == "unparsed":
        flags.append(f"коэффициент модели не разобран: {authored_coeff}")
        completeness_reasons.append("coefficient_unparsed")
    elif application == "unrecognized":
        flags.append(
            "коэффициент модели не применён: область применения "
            f"{coeff_meta.get('applies_to')!r} не из labor/machine/labor_and_machine"
        )
        completeness_reasons.append("coefficient_application_unrecognized")
    elif application == "missing":
        flags.append("коэффициент модели не применён: область применения не указана")
        completeness_reasons.append("coefficient_application_missing")
    elif application == "applied" and (k_ozp != 1.0 or k_em != 1.0) and not coefficient_basis:
        flags.append("числовой коэффициент модели без evidence_refs/основания")
        completeness_reasons.append("coefficient_source_missing")
    if position.get("source_coefficient_overlap"):
        flags.append(
            "исходный объём уже содержит коэффициент; модель дополнительно задала k "
            "к ОЗП/ЭМ. Количество не умножается повторно, но есть риск двойного применения"
        )

    review_was_required = "resource_review_status" in position
    resource_review_status = str(position.get("resource_review_status") or "not_required_raw_trace")
    resource_review_reason = str(position.get("resource_review_reason") or "")
    if review_was_required and resource_review_status not in {"keep_all_confirmed", "actions_confirmed"}:
        flags.append("ресурсный состав нормы не подтверждён моделью" + (f": {resource_review_reason}" if resource_review_reason else ""))
        completeness_reasons.append("resource_review_unresolved")
    component_review = {
        "labor": (
            str(position.get("labor_review_status") or ""),
            str(position.get("labor_review_reason") or ""),
        ),
        "machine": (
            str(position.get("machine_review_status") or ""),
            str(position.get("machine_review_reason") or ""),
        ),
        "material": (
            str(position.get("material_review_status") or ""),
            str(position.get("material_review_reason") or ""),
        ),
    }
    for component, (status, reason) in component_review.items():
        if status and status not in {"confirmed", "not_present"}:
            flags.append(
                f"компонент {component} не подтверждён моделью"
                + (f": {reason}" if reason else "")
            )
            completeness_reasons.append(f"{component}_review_unresolved")

    work_code = position.get("code") or (norm or {}).get("code") or ""
    work_name = position.get("name") or (norm or {}).get("name") or ""
    work_unit = position.get("unit") or (norm or {}).get("unit") or ""
    nr_sp = nr_sp_service.resolve(
        work_name,
        code=work_code,
        rule_id=str(position.get("nr_sp_rule_id") or "") or None,
    )
    authored_nr = position.get("nr_pct") if position.get("nr_pct") not in (None, "") else None
    authored_sp = position.get("sp_pct") if position.get("sp_pct") not in (None, "") else None
    # An accrual rate needs an owner the same way a price does (ADR-16 § 7):
    # the operator's own number, or a rule the fail-closed catalog could pick
    # unambiguously.  A percentage printed inside the norm card belongs to
    # neither owner, so it may still be calculated but never silently closes
    # the position -- § 11 №6 lists НР and СП among the things a known price
    # must not mask.
    nr_source = ""
    sp_source = ""
    if authored_nr is not None:
        nr_pct: float | None = _f(authored_nr)
        nr_ready = True
        nr_source = "explicit"
    elif str(nr_sp.get("status") or "").startswith("resolved") and nr_sp.get("nr_pct") not in (None, ""):
        nr_pct = _f(nr_sp.get("nr_pct"))
        nr_ready = True
        nr_source = "catalog"
    elif (norm or {}).get("nr_pct") not in (None, ""):
        nr_pct = _f((norm or {}).get("nr_pct"))
        nr_ready = True
        nr_source = "norm_card"
    else:
        nr_pct = None
        nr_ready = False
    if authored_sp is not None:
        sp_pct: float | None = _f(authored_sp)
        sp_ready = True
        sp_source = "explicit"
    elif str(nr_sp.get("status") or "").startswith("resolved") and nr_sp.get("sp_pct") not in (None, ""):
        sp_pct = _f(nr_sp.get("sp_pct"))
        sp_ready = True
        sp_source = "catalog"
    elif (norm or {}).get("sp_pct") not in (None, ""):
        sp_pct = _f((norm or {}).get("sp_pct"))
        sp_ready = True
        sp_source = "norm_card"
    else:
        sp_pct = None
        sp_ready = False
    if not nr_ready or not sp_ready:
        flags.append("НР/СП не разрешены по виду работ: нужен нормативный источник/явный выбор")
        completeness_reasons.append("nr_sp_unresolved")
    nr_sp_ownership = {
        "label": "",
        "nr_pct": nr_pct,
        "sp_pct": sp_pct,
        "nr_source": nr_source,
        "sp_source": sp_source,
        "catalog_status": str(nr_sp.get("status") or ""),
        "basis": str(nr_sp.get("basis") or ""),
        "rule_id": str(nr_sp.get("rule_id") or ""),
    }
    if nr_source == "norm_card" or sp_source == "norm_card":
        # named exactly like the resource-level card price so every channel that
        # shows an unowned number shows this one too
        nr_sp_ownership["label"] = "nr_sp_without_basis"
        rates = ", ".join(
            f"{label} {value:g} %"
            for label, value in (("НР", nr_pct), ("СП", sp_pct))
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        )
        flags.append(
            "НР/СП взяты из карточки нормы"
            + (f" ({rates})" if rates else "")
            + ", а не из нормативного основания или явного выбора оператора"
        )
        completeness_reasons.append("nr_sp_without_basis")
    elif not nr_ready or not sp_ready:
        nr_sp_ownership["label"] = "nr_sp_unresolved"

    detail_rows: dict[str, list[dict[str, Any]]] = {"labor": [], "machine": [], "machinist": [], "material": []}
    sums = {"labor": 0.0, "machine": 0.0, "machinist": 0.0, "material": 0.0}
    qty_sums = {"labor": 0.0, "machine": 0.0, "machinist": 0.0, "material": 0.0}
    card_prices: list[dict[str, Any]] = []
    # Task 2026-09-29 § 4 (tracker #54): the calculator states one decision per
    # resource it looked at — the same numbers the document prints — so the check
    # sheet can name each resource with the price fact that settled it.  Reading
    # the input position instead would show what the model proposed, not what was
    # priced, and on the visible-rows route the input carries no resources at all
    # (the norm expands them inside the calculator).
    resource_decisions: list[dict[str, Any]] = []

    for res in resources:
        kind = str(res.get("kind") or "")
        coeff = _resource_coeff(kind, k_ozp=k_ozp, k_em=k_em)
        per_unit = gesn_service._optional_quantity(res.get("per_unit"))
        total_qty = (
            gesn_service._optional_quantity(per_unit * coeff * work_qty)
            if per_unit is not None else None
        )
        if total_qty is not None:
            total_qty = round(total_qty, 6)
        else:
            flags.append(f"неизвестный расход: {res.get('name', '?')} ({res.get('code', '—')})")
            completeness_reasons.append(f"quantity_missing:{res.get('code') or res.get('name') or '?'}")
        price = _resolve_price_trace(res, pricebook=pricebook, kac_map=kac_lookup)
        if (price.price is None and price.action == "needs_machinist_rate"
                and kind == "machinist" and not str(res.get("code") or "").strip()
                and fsem_trace.get("status") == "unresolved"):
            # This anonymous aggregate cannot be priced until its source hours
            # reconcile with FSEM. A tariff alone cannot repair that conflict.
            # Keep the price, quantity and monetary completeness unchanged.
            price = replace(price, action="needs_fsem_resolution")
        cost = (
            gesn_service._optional_quantity(total_qty * price.price)
            if total_qty is not None and price.price is not None else None
        )
        if cost is not None:
            cost = (round_numeric_measure_amount(cost)
                    if price.unit_conversion and price.unit_conversion.get("conversion_kind") == "numeric_measure"
                    else round(cost, 2))
        elif total_qty is not None and price.price is not None:
            flags.append(f"стоимость ресурса вне числового диапазона: {res.get('name', '?')}")
            completeness_reasons.append(f"resource_amount_nonfinite:{res.get('code') or res.get('name') or '?'}")
        if price.book_unit:
            flags.append(book_unit_conflict_note(res, price.book_unit))
        if price.price is None:
            if price.action != BOOK_UNIT_CONFLICT_ACTION:
                # The dedicated note above already names what is missing here, so
                # the resource is not reported twice with two different wordings.
                action_label = price_action_label(price.action, price.source)
                flags.append(f"{action_label}: {res.get('name','?')} ({res.get('code','—')})")
            completeness_reasons.append(f"price_missing:{res.get('code') or res.get('name') or '?'}")
            if price.action == "model_price_unit_conflict":
                completeness_reasons.append(f"model_price_unit_conflict:{res.get('code') or res.get('name') or '?'}")
                flags.append(
                    f"Цена {res.get('price')} за «{res.get('price_unit')}» сохранена, но не применена "
                    f"к количеству в «{res.get('unit')}»: нет обоснованного перевода единиц"
                )
            if price.record_conflict:
                completeness_reasons.append(f"ambiguous_price_record:{res.get('code') or res.get('name') or '?'}")
        elif price.action == "card_price_without_basis":
            # Money exists, but nobody owns the number: it stays in the document,
            # is reported as a price gap, breaks the position's completeness and
            # is never counted as a confirmed amount (ADR-16 § 7, § 12).
            card_prices.append(
                {
                    "kind": kind,
                    "code": str(res.get("code") or ""),
                    "name": str(res.get("name") or ""),
                    "unit": str(res.get("unit") or ""),
                    "price": price.price,
                    "cost": cost,
                }
            )
            flags.append(
                "цена взята из карточки нормы, а не из выбранной ценовой базы или КАЦ: "
                f"{res.get('name','?')} ({res.get('code','—')})"
            )
            completeness_reasons.append(
                f"card_price_without_basis:{res.get('code') or res.get('name') or '?'}"
            )
        elif price.action in {"kac_without_source_unit", "model_price_without_basis", "book_price_unit_unknown"}:
            flags.append(f"{price_action_label(price.action)}: {res.get('name', '?')}")
            completeness_reasons.append(f"{price.action}:{res.get('code') or res.get('name') or '?'}")
        # § 4: which price hole this resource leaves, in the calculator's own words.
        # A resource priced from the chosen book or КАЦ has none; money that exists
        # only because the norm card writes it is still a hole (ADR-16 § 7).
        gap_action = (
            ""
            if price.price is not None and price.action not in {
                "card_price_without_basis", "kac_without_source_unit", "model_price_without_basis", "book_price_unit_unknown",
            }
            else str(price.action or price.source or "")
        )
        resource_decisions.append(
            {
                "kind": kind,
                "code": str(res.get("code") or ""),
                "name": str(res.get("name") or ""),
                "unit": str(res.get("unit") or ""),
                "per_unit": per_unit,
                "qty": total_qty,
                "price": price.price,
                "cost": cost,
                "price_action": price.action or "",
                # § 4 / tracker #56: the decision says which kind of price hole it
                # left, in the same words the flag above uses, so the file names the
                # gap instead of only saying that money is missing.
                "price_gap_kind": price_action_label(gap_action) if gap_action else "",
                "price_basis": price.basis or "",
                "price_source": price.source or "",
                "price_book_unit": price.book_unit or "",
                **{key: res[key] for key in ("price_unit", "price_quantity_trace") if key in res},
                **({"quoted_price": res.get("price")} if res.get("price_origin") == "model_result" else {}),
                **({"price_unit_conversion": dict(price.unit_conversion)} if price.unit_conversion else {}),
                **({"price_record_conflict": dict(price.record_conflict)} if price.record_conflict else {}),
                "resource_group": str((price.group or {}).get("group") or ""),
                "code_derivation": str(res.get("code_derivation") or ""),
                **{key: res[key] for key in (
                    "machinist_basis", "fsem_machine_code", "fsem_crew_hours", "fsem_driver_grade", "fsem_source_page",
                ) if key in res},
                **({"resource_binding": dict(res["resource_binding"])} if isinstance(res.get("resource_binding"), Mapping) else {}),
            }
        )
        if kind not in detail_rows:
            flags.append(f"неизвестный вид ресурса: {kind!r}")
            continue
        if cost is not None:
            sums[kind] = round(sums[kind] + cost, 2)
        qty_sums[kind] = (
            round(qty_sums[kind] + total_qty, 6)
            if qty_sums[kind] is not None and total_qty is not None else None
        )
        detail_rows[kind].append(
            _row(
                f"resource_{kind}",
                str(res.get("name") or ""),
                columns={
                    2: res.get("code") or "",
                    3: res.get("name") or "",
                    4: res.get("unit") or "",
                    5: per_unit,
                    6: coeff,
                    7: total_qty,
                    8: price.column_8,
                    9: price.column_9,
                    10: price.column_10,
                    11: 1,
                    12: cost,
                },
                source=price.source,
                meta={
                    "basis": price.basis,
                    "kind": kind,
                    "price_action": price.action,
                    "price_book_unit": price.book_unit,
                    **{key: res[key] for key in ("price_unit", "price_quantity_trace") if key in res},
                    **({"quoted_price": res.get("price")} if res.get("price_origin") == "model_result" else {}),
                    **({"price_unit_conversion": dict(price.unit_conversion)} if price.unit_conversion else {}),
                    "price_source_ref": res.get("price_source_ref") or "",
                    "resource_binding": res.get("resource_binding") or {},
                    **{key: res[key] for key in (
                        "machinist_basis", "fsem_machine_code", "fsem_crew_hours", "fsem_driver_grade", "fsem_source_page",
                    ) if key in res},
                    # § 3: a group reference arrives at the operator with the concrete
                    # resources of the book attached, because the answer to it is a
                    # choice of one of them and not a number.
                    "price_resource_group": str((price.group or {}).get("group") or ""),
                    "price_resource_candidates": list(
                        (price.group or {}).get("members") or []
                    ),
                },
            )
        )

    ozp = sums["labor"]
    zpm = sums["machinist"]
    em = round(sums["machine"] + zpm, 2)
    mat = sums["material"]
    direct = round(ozp + em + mat, 2)
    fot = round(ozp + zpm, 2)
    nr = round(fot * nr_pct / 100, 2) if nr_pct is not None else None
    sp = round(fot * sp_pct / 100, 2) if sp_pct is not None else None
    total = direct
    if nr is not None:
        total = round(total + nr, 2)
    if sp is not None:
        total = round(total + sp, 2)
    full_amount = total if not completeness_reasons else None
    position_total_label = "Всего по позиции" if full_amount is not None else "Известная стоимость позиции"
    # An operator-confirmed price addressed to this operation applies to exactly
    # this calculated position: the position total becomes qty x price, and the
    # amount is confirmed. Norm resource rows and direct-cost subtotals above
    # stay visible as the norm's own composition (reference); no other
    # operation on the locator is touched.
    operator_price = _num(position.get("confirmed_price"))
    operator_price_trace: dict[str, Any] = {}
    if operator_price is not None and math.isfinite(operator_price):
        attributed = position.get("confirmed_price_attributed") is not False
        price_owner = str(position.get("price_owner") or "operator") if attributed else ""
        price_kind = str(position.get("confirmed_price_kind") or "").strip()
        price_qty = work_qty
        price_unit = work_unit
        price_issue = str(position.get("confirmed_price_issue") or "")
        if "confirmed_price_kind" in position and (
            price_owner != "operator" or price_kind in {"unit_price", "position_total"}
        ):
            if price_kind == "position_total":
                price_qty = 1.0
                price_unit = "позиция"
            elif price_kind == "unit_price":
                price_qty = _num(position.get("confirmed_price_quantity"))
                price_unit = str(position.get("confirmed_price_unit") or "")
                if price_qty is None:
                    attributed = False
                    price_issue = price_issue or "position_price_unit_conflict"
            else:
                price_qty = None
                attributed = False
                price_issue = "position_price_kind_unknown"
        operator_cost = round(price_qty * operator_price, 2) if price_qty is not None else None
        norm_known = total
        if operator_cost is not None:
            direct = operator_cost
            total = operator_cost
        full_amount = operator_cost if attributed else None
        position_total_label = (
            "Всего по позиции (цена подтверждена оператором)" if price_owner == "operator"
            else "Всего по позиции (цена подтверждена источником)" if attributed
            else "Известная стоимость позиции (цена без подтверждённого источника)"
        )
        # § 4: the unit the confirmed price was multiplied by has to be in the file.
        # A position is measured in the norm's unit (often «100 м2»), while the source
        # ВОР states its own; an operator answering «100 рублей за единицу» without
        # seeing which unit the document uses would get a sum off by that factor, so
        # the line names the unit, the quantity it was applied to, and what the source
        # row stated.  Nothing is recomputed here — the numbers stay the calculator's.
        note_prefix = (
            OPERATOR_PRICE_NOTE_PREFIX if price_owner == "operator"
            else SOURCE_PRICE_NOTE_PREFIX if attributed else "итог позиции взят по неподтверждённой цене модели"
        )
        unit_note = (
            f"{note_prefix}: {operator_price} ₽ за "
            f"«{price_unit or '?'}» × {price_qty} = {operator_cost} ₽, а не по ресурсному "
            "составу нормы"
        ) if operator_cost is not None else (
            f"Цена {operator_price} ₽ за «{price_unit or '?'}» сохранена, но не применена: "
            "нет обоснованного перевода исходного количества в единицу цены"
        )
        source_qty = _num(position.get("source_quantity"))
        source_unit = str(position.get("source_unit") or "").strip()
        if source_unit and source_unit != str(work_unit or "").strip() and (
            price_owner == "operator" or price_kind not in {"unit_price", "position_total"}
        ):
            unit_note += (
                f"; в исходной строке {source_qty if source_qty is not None else '?'} "
                f"«{source_unit}» — если цена названа за исходную единицу, её нужно "
                "переписать в этом количестве"
            )
        flags.append(unit_note)
        if not attributed:
            completeness_reasons.append(f"position_price_without_basis:{work_code or work_name}")
        if price_issue:
            completeness_reasons.append(f"{price_issue}:{work_code or work_name}")
            flags.append(f"{price_issue}:{work_code or work_name}")
        operator_price_trace = {
            "status": (
                "operator_confirmed_position_price" if price_owner == "operator"
                else "source_confirmed_position_price" if attributed else "position_price_without_basis"
            ),
            "price": operator_price,
            "qty": price_qty,
            "cost": operator_cost,
            "norm_known": norm_known,
            # the unit the multiplication used, stated apart from the source unit (§ 4)
            "unit": str(price_unit or ""),
            "price_kind": price_kind or ("operator_unit_price" if price_owner == "operator" else ""),
            "source_unit": str(position.get("source_unit") or ""),
            "source_quantity": source_qty,
            **({"quantity_trace": position["confirmed_price_quantity_trace"]}
               if "confirmed_price_quantity_trace" in position else {}),
            "unit_note": unit_note,
            "source": str(position.get("price_source") or ("operator" if price_owner == "operator" else "")),
        }

    rows: list[dict[str, Any]] = [
        _row(
            "work",
            work_name,
            columns={2: work_code, 3: work_name, 4: work_unit, 5: work_qty, 6: 1, 7: work_qty},
            source="gesn",
            meta={
                "official_name": position.get("official_name") or (norm or {}).get("name") or "",
                "selection_kind": position.get("selection_kind") or "",
                "is_analog": bool(position.get("is_analog")),
                "analog_limitations": list(position.get("analog_limitations") or []),
                "binding_reason": position.get("binding_reason") or "",
                "analogue": position.get("analogue") or "",
                "coverage": position.get("coverage") or "",
                "quantity_trace": position.get("quantity_trace") or {},
                "row_role": position.get("row_role") or "",
                "work_row": position.get("work_row") or "",
                "source_quantity": position.get("source_quantity"),
                "source_unit": position.get("source_unit") or "",
                "evidence_refs": list(
                    dict.fromkeys(
                        list(coeff_meta.get("refs") or [])
                        + list(position.get("evidence_refs") or [])
                    )
                ),
            },
        ),
    ]
    show_coeff_row = (
        k_ozp != 1.0
        or k_em != 1.0
        or application in {"missing", "unparsed", "unrecognized"}
        or (
            authored_coeff not in (None, "")
            and not (
                isinstance(authored_coeff, int | float)
                and not isinstance(authored_coeff, bool)
                and float(authored_coeff) == 1.0
            )
            and str(authored_coeff).strip() not in {"1", "1.0", "1,0"}
        )
    )
    if show_coeff_row:
        if application == "unparsed":
            label = f"Коэффициент модели не разобран: {authored_coeff}"
        elif application in {"missing", "unrecognized"}:
            label = f"Коэффициент модели не применён: {authored_coeff}"
        else:
            label = coefficient_basis or "Повышающие коэффициенты"
        coeff_columns: dict[int, Any] = {3: label, 6: 1}
        if (
            application in {"missing", "unrecognized"}
            and isinstance(authored_coeff, int | float)
            and not isinstance(authored_coeff, bool)
        ):
            coeff_columns[6] = authored_coeff
        coeff_meta_row: dict[str, Any] = {"k_ozp": k_ozp, "k_em": k_em}
        if authored_coeff not in (None, ""):
            coeff_meta_row["coefficient"] = authored_coeff
        if coeff_meta.get("applies_to"):
            coeff_meta_row["coefficient_applies_to"] = coeff_meta.get("applies_to")
        if application:
            coeff_meta_row["coefficient_application"] = application
        if coeff_meta.get("refs"):
            coeff_meta_row["evidence_refs"] = list(coeff_meta.get("refs") or [])
        rows.append(
            _row(
                "coefficient",
                label,
                columns=coeff_columns,
                source="coefficient",
                meta=coeff_meta_row,
            )
        )

    if (uncomputed_components or resource_binding_conflicts or position.get("norm_card_body_unread")
            or any(reason.startswith(("quantity_missing:", "resource_amount_nonfinite:")) for reason in completeness_reasons)):
        # An attributed position price cannot hide an unapplied resource action.
        # Nor can it certify an unknown quantity in the selected composition.
        full_amount = None
    if uncomputed_components:
        position_total_label = "Известная стоимость позиции"
    rows.extend(
        [
            _row("group_labor", "ОТ(ЗТ)", columns={3: "ОТ(ЗТ)", 4: "чел.-ч", 7: qty_sums["labor"], 12: ozp}),
            *detail_rows["labor"],
            _row("group_machine", "ЭМ", columns={3: "ЭМ", 12: em}),
            *detail_rows["machine"],
            _row("group_machinist", "ОТм(ЗТм)", columns={3: "ОТм(ЗТм)", 4: "чел.-ч", 7: qty_sums["machinist"], 12: zpm}),
            *detail_rows["machinist"],
            _row("group_material", "М", columns={3: "М", 12: mat}),
            *detail_rows["material"],
            _row("direct_total", "Итого прямые затраты", columns={3: "Итого прямые затраты", 12: direct}),
            _row("fot", "ФОТ", columns={3: "ФОТ", 12: fot}),
            _row(
                "nr",
                "НР",
                columns={3: "НР", 4: "%", 5: nr_pct, 7: nr_pct, 12: nr},
                source="Пр/812" if nr_ready else "нужен норматив",
            ),
            _row(
                "sp",
                "СП",
                columns={3: "СП", 4: "%", 5: sp_pct, 7: sp_pct, 12: sp},
                source="Пр/774" if sp_ready else "нужен норматив",
            ),
            _row(
                "position_total",
                position_total_label,
                columns={3: position_total_label, 12: total},
                meta={
                    "amount_status": "complete" if full_amount is not None else "partial",
                    "completeness_reasons": list(dict.fromkeys(completeness_reasons)),
                    **(
                        {"operator_confirmed_price": operator_cost}
                        if operator_price_trace
                        else {}
                    ),
                },
            ),
        ]
    )

    return {
        "code": work_code,
        "name": work_name,
        "unit": work_unit,
        "qty": work_qty,
        "rows": rows,
        "summary": {
            "ozp": ozp,
            "machine": sums["machine"],
            "zpm": zpm,
            "em": em,
            "mat": mat,
            "direct": direct,
            "fot": fot,
            "nr_pct": nr_pct,
            "sp_pct": sp_pct,
            "nr": nr,
            "sp": sp,
            "total": total,
            "known_amount": total,
            "full_amount": full_amount,
            "amount_status": "complete" if full_amount is not None else "partial",
            # ADR-16 § 7: money whose only owner is the norm card itself is named
            # here so the header, the checklist and the readiness agree that the
            # position is a draft even though an amount exists.
            "card_priced_resources": card_prices,
            "operator_price_trace": operator_price_trace,
            # Directive 2.3: when an operator supplied a confirmed unit price the
            # norm-derived resource amounts stay visible in the document as
            # reference, but they must NOT be re-counted in the estimate-level
            # aggregate direct / fot / nr / sp / machine / em / mat / ozp / zpm.
            # The flag is set here (build_position_trace) so build_lsr_trace's
            # summary loop, which runs before the caller can annotate, honors it.
            "resource_reference_only": bool(
                isinstance(operator_price_trace, Mapping)
                and operator_price_trace.get("cost") is not None
                and operator_price_trace.get("status") in {
                    "operator_confirmed_position_price", "source_confirmed_position_price", "position_price_without_basis",
                }
            ),
            "completeness_reasons": list(dict.fromkeys(completeness_reasons)),
            "resource_review_status": resource_review_status,
            "resource_review_reason": resource_review_reason,
            "component_review": component_review,
            # § 4 (tracker #54): one stated decision per resource the calculator
            # priced, from the same numbers the document prints.
            "resource_decisions": resource_decisions,
            **({
                "resource_binding_audit": list(position.get("resource_binding_audit") or []),
                "resource_binding_conflicts": resource_binding_conflicts,
                **{key: position[key] for key in ("resource_bindings", "resource_review", "separate_supply_review_audit") if key in position},
            } if "resource_bindings" in position or "resource_review" in position or resource_binding_conflicts else {}),
            "labor_qty": qty_sums["labor"],
            "machinist_qty": qty_sums["machinist"],
            "flags": flags,
            "norm_source_integrity": norm_source_integrity,
            **({"normative_source_snapshot": {
                "norm_key": str(norm.get("key") or qualified_norm_key(position.get("code"))),
                "sha256": str(norm["_source_sha256"]),
                "source_kind": str(norm.get("_source_kind") or ""),
                "source_path": str(norm.get("_source_path") or ""),
            }} if norm and norm.get("_source_sha256") else {}),
            "nr_sp_trace": nr_sp,
            # the owner of the accrual rate, so the file and the chat can name
            # a card-written НР/СП as the open question it is
            "nr_sp_ownership": nr_sp_ownership,
            "fsem_trace": fsem_trace,
            "labor_code_trace": labor_code_trace,
        },
    }


def build_lsr_trace(
    positions: list[dict[str, Any]],
    *,
    pricebook=None,
    kac_map: dict[str, float] | None = None,
    k_ozp: float = 1.0,
    k_em: float = 1.0,
    coefficient_basis: str = "",
    name: str = "",
) -> dict[str, Any]:
    """Многопозиционная РИМ-трасса ЛСР: позиции по разделам + итоги разделов + общий свод.

    Каждая позиция строится через :func:`build_position_trace` — числа те же, gold позиции сохраняется
    (один общий калькулятор, не дубль). Разделы — по полю ``position["section"]`` (порядок первого
    появления, позиции одного раздела группируются вместе). Свод — Σ позиций (код, не LLM):
    прямые/ФОТ/НР/СП/Всего и нормативные чел.-ч рабочих/машинистов для шапки формы.
    """
    sections: list[dict[str, Any]] = []
    by_section: dict[str, dict[str, Any]] = {}
    for pos in positions or []:
        trace = build_position_trace(
            pos,
            pricebook=pricebook,
            kac_map=kac_map,
            k_ozp=k_ozp,
            k_em=k_em,
            coefficient_basis=coefficient_basis,
        )
        sec_name = str(pos.get("section") or "").strip() or "Без раздела"
        trace = {**trace, "section": sec_name}
        if pos.get("work_id") is not None:
            trace["work_id"] = pos.get("work_id")
        if pos.get("source_row") is not None:
            trace["source_row"] = pos.get("source_row")
        if pos.get("op_key") is not None:
            trace["op_key"] = pos.get("op_key")
        if pos.get("source_refs") is not None:
            trace["source_refs"] = list(pos.get("source_refs") or [])
        if pos.get("evidence_refs") is not None:
            trace["evidence_refs"] = list(pos.get("evidence_refs") or [])
        if pos.get("coefficient") not in (None, ""):
            trace["coefficient"] = pos.get("coefficient")
        if pos.get("coefficient_applies_to"):
            trace["coefficient_applies_to"] = pos.get("coefficient_applies_to")
        if pos.get("coefficient_application"):
            trace["coefficient_application"] = pos.get("coefficient_application")
        entry = by_section.get(sec_name)
        if entry is None:
            entry = {"section": sec_name, "positions": [], "total": 0.0}
            by_section[sec_name] = entry
            sections.append(entry)
        entry["positions"].append(trace)
        entry["total"] = round(
            entry["total"] + _f(trace["summary"].get("known_amount", trace["summary"]["total"])),
            2,
        )

    # Task 2026-09-29 § 4: the delivered document numbers its positions continuously
    # across sections, so the number is stamped on the trace here and the check sheet
    # can point at the same line of the file the operator opens.  The renderer's own
    # counter prints the identical sequence — it advances once per «работа» row, and a
    # position has exactly one — so nothing is numbered twice.
    position_no = 0
    for entry in sections:
        for trace in entry["positions"]:
            position_no += 1
            trace["position_no"] = position_no
            trace["summary"]["position_no"] = position_no

    money_keys = ("ozp", "zpm", "machine", "em", "mat", "direct", "fot", "nr", "sp", "total")
    # Directive 2.3: on operator-replaced positions the "total" flows through
    # the estimate; the resource-level components are reference-only and must
    # not inflate the aggregate direct / fot / nr / sp / machine / em / mat.
    _resource_keys = ("ozp", "zpm", "machine", "em", "mat", "direct", "fot", "nr", "sp")
    summary: dict[str, Any] = {k: 0.0 for k in money_keys}
    summary["labor_qty"] = 0.0
    summary["machinist_qty"] = 0.0
    summary["reference_only_positions"] = 0
    flags: list[str] = []
    all_positions_complete = True
    count = 0
    for entry in sections:
        for trace in entry["positions"]:
            s = trace["summary"]
            reference_only = bool(s.get("resource_reference_only"))
            for k in money_keys:
                if reference_only and k in _resource_keys:
                    continue
                value = s.get(k)
                if value is None:
                    continue
                summary[k] = round(summary[k] + _f(value), 2)
            if not reference_only:
                for quantity_key in ("labor_qty", "machinist_qty"):
                    value = s.get(quantity_key)
                    summary[quantity_key] = (
                        round(summary[quantity_key] + value, 6)
                        if summary[quantity_key] is not None and value is not None else None
                    )
            else:
                summary["reference_only_positions"] += 1
            flags.extend(s.get("flags") or [])
            all_positions_complete = all_positions_complete and s.get("full_amount") is not None
            count += 1
    summary["positions"] = count
    summary["flags"] = flags
    summary["known_amount"] = summary["total"]
    summary["full_amount"] = summary["total"] if count and all_positions_complete else None
    summary["amount_status"] = "complete" if summary["full_amount"] is not None else "partial"
    if count and all_positions_complete and not gap_flags(flags):
        summary["result_status"] = "priced_final"
    elif count:
        summary["result_status"] = "priced_partial"
    else:
        summary["result_status"] = "norm_selection_required"

    component_warnings = [warning for position in positions or []
                          for warning in _norm_components_audit_warnings(position)]
    return {"name": name or "", "sections": sections, "summary": summary,
            **({"warnings": component_warnings} if component_warnings else {})}


_NEGATIVE_COVERAGE_EXACT = {
    "нет",
    "н/д",
    "n/a",
    "na",
    "none",
    "нет соответствия",
    "не соответствует",
}
_NEGATIVE_COVERAGE_PHRASES = (
    "норма не соответствует",
    "нет прямого аналога",
    "нет подходящего аналога",
    "отсутствует аналог",
    "не соответствует норме",
    "не является аналогом",
)


def _coverage_marker_text(value: Any) -> str:
    marker = str(value or "").strip().strip("*_` ").strip()
    if len(marker) >= 2 and (marker[0], marker[-1]) in {("(", ")"), ("[", "]")}:
        marker = marker[1:-1].strip()
    marker = marker.strip(".,;:").strip()
    return " ".join(marker.casefold().replace("ё", "е").split())


def model_row_rejects_selected_norm(row: Mapping[str, Any] | None) -> tuple[bool, str]:
    """True when the model itself refused the selected card.

    Code does not choose between montage and dismantling: it never rewrites the
    model's cipher.  It only honors an explicit authored coverage/analogue
    refusal and leaves the row visible as MISSING.  A pairing where the two
    texts name opposite actions is handled by :func:`norm_action_conflict`,
    which asks instead of deciding.
    """
    payload = row if isinstance(row, Mapping) else {}
    for key in ("coverage", "analogue", "note"):
        marker = _coverage_marker_text(payload.get(key))
        if not marker:
            continue
        if marker in _NEGATIVE_COVERAGE_EXACT:
            return True, f"модель отклонила норму: {key}={marker}"
        for phrase in _NEGATIVE_COVERAGE_PHRASES:
            if phrase in marker:
                return True, f"модель отклонила норму: {key} содержит «{phrase}»"
    return False, ""


def norm_action_conflict(row_title: Any, norm: Mapping[str, Any] | None) -> dict[str, str]:
    """A verbatim reversal between the operation the row names and the card names.

    Task § 11 №8: «демонтаж» must not be delivered as «монтаж».  This reads the
    two texts that are already in the document and states one structural fact:
    each side names exactly one action and the actions are opposite.  It chooses
    no norm, edits no cipher, recomputes no number and infers no technology — it
    removes only the claim that applicability is substantiated, and puts one
    concrete question in every channel that shows the row (ADR-16 § 6, § 10).

    Returns ``{}`` when nothing contradicts, including every ambiguous case.
    """

    card = norm if isinstance(norm, Mapping) else {}
    norm_title = str(card.get("name") or card.get("title") or "").strip()
    pair = reversed_action_pair(row_title, norm_title)
    if not pair:
        return {}
    row_action, norm_action = pair
    return {
        "row_action": row_action,
        "norm_action": norm_action,
        "norm_title": norm_title,
        "message": (
            f"в строке названа операция «{row_action}», а в названии выбранной "
            f"нормы — «{norm_action}»: подтвердите операцию или выберите другую "
            "норму; код норму не подменяет"
        ),
    }


def _code_from_visible_row(row: dict[str, Any]) -> str:
    # An explicit code cell is not prose. A shifted explanation may mention a
    # rejected norm; extracting its first code would manufacture a selection.
    for key in ("code", "norm_code"):
        if row.get(key) not in (None, ""):
            value = str(row[key]).strip().strip("`* ")
            return _extract_norm_code(value) if _NORM_REF_RE.fullmatch(value) else ""
    explicit = _first_value(row, "code", "norm_code", "basis", "justification", "обоснование")
    return _extract_norm_code(explicit)


_SOURCE_COEFFICIENT_HINT = re.compile(
    r"(?i)коэфф|с\s+к(?:оэф)?\s*[=:]|×\s*1[.,]\d|x\s*1[.,]\d|[*×x]\s*1[.,]5"
)


def _visible_row_quantity_already_includes_coefficient(
    row: Mapping[str, Any],
    *,
    title: str,
    raw_qty_text: str,
) -> bool:
    blob = " ".join(
        str(value)
        for value in (
            raw_qty_text,
            title,
            row.get("note"),
            row.get("coverage"),
            row.get("comment"),
            row.get("remark"),
        )
        if value not in (None, "")
    )
    return bool(_SOURCE_COEFFICIENT_HINT.search(blob))


def _quantity_from_visible_row(row: dict[str, Any]) -> tuple[float | None, str, str]:
    raw_qty = _first_value(
        row,
        "qty",
        "quantity",
        "quantity_total",
        "volume",
        "amount_qty",
        "количество",
        "кол-во",
        "объем",
        "объём",
    )
    qty = _num(raw_qty)
    if qty is not None and not math.isfinite(qty):
        qty = None
    unit = str(_first_value(row, "unit", "ед", "ед.", "единица", "единица измерения") or "").strip()
    return qty, unit, str(raw_qty or "")


_GAP_UNCONFIRMED_BASIS = (
    "нужно основание пересчёта: conversion_factor или calc_quantity "
    "вместе с conversion_source (фасовка, длина секции, масса, коэффициент)"
)


def _unconfirmed_source_change(
    row: Mapping[str, Any],
    *,
    source_qty: float | None,
    source_unit: str,
) -> dict[str, Any] | None:
    """True when the authored quantity/unit silently changed against the source.

    The catalog facts (``_catalog_source_*``) are stamped by the workbook
    adapter from the server-owned attachment. A declared conversion basis is
    an explicit recalculation ground; its arithmetic is still verified later
    in :func:`_norm_qty_from_visible_row`. Code never fixes the model here:
    it reports field, source value, received value, and the needed input.
    """

    values = row.get("_catalog_source_values")
    numbers = row.get("_catalog_source_numbers")
    if not isinstance(values, list) and not isinstance(numbers, list):
        return None
    basis = str(
        row.get("conversion_source") or row.get("quantity_source") or ""
    ).strip()
    if basis and any(
        (number := _num(row.get(field))) is not None and math.isfinite(number)
        for field in ("calc_quantity", "conversion_factor")
    ):
        return None
    unit_norm = normalize_unit(source_unit)
    comparable_qty = source_qty
    if unit_norm not in {"", "-", "—", "–"} and isinstance(values, list) and values:
        if "_catalog_source_unit" in row:
            catalog_factor, catalog_base = norm_measure(row["_catalog_source_unit"])
            authored_factor, authored_base = norm_measure(source_unit)
            unit_matches = bool(
                normalize_unit(catalog_base)
                and normalize_unit(catalog_base) == normalize_unit(authored_base)
                and math.isfinite(catalog_factor) and catalog_factor > 0
                and math.isfinite(authored_factor) and authored_factor > 0
            )
            if unit_matches and source_qty is not None:
                comparable_qty = source_qty * authored_factor / catalog_factor
        else:
            cell_units = {normalize_unit(item) for item in values}
            joined = normalize_unit(" ".join(str(item) for item in values))
            unit_matches = unit_norm in cell_units or unit_norm in joined
        if not unit_matches:
            return {
                "field": "unit",
                "source_value": " / ".join(
                    dict.fromkeys(str(item).strip() for item in values if str(item).strip())
                )[:160],
                "authored_value": source_unit,
                "needed": _GAP_UNCONFIRMED_BASIS,
                "message": (
                    f"единица «{source_unit}» не встречается в исходной строке; "
                    "изменение единицы без основания пересчёта не рассчитывается"
                ),
            }
    if (
        isinstance(numbers, list)
        and numbers
        and source_qty is not None
        and not any(quantities_close(float(comparable_qty), float(item)) for item in numbers)
    ):
        return {
            "field": "quantity",
            "source_value": ", ".join(f"{item:g}" for item in numbers[:8]),
            "authored_value": source_qty,
            "needed": _GAP_UNCONFIRMED_BASIS,
            "message": (
                f"количество {source_qty:g} не совпадает с исходником "
                f"({', '.join(f'{item:g}' for item in numbers[:3])}); "
                "изменение количества без основания пересчёта не рассчитывается"
            ),
        }
    if (
        isinstance(numbers, list)
        and not numbers
        and source_qty is not None
        and row.get("_catalog_source_quantity_known")
    ):
        return {
            "field": "quantity",
            "source_value": "столбец количества распознан, но значение не подтверждено",
            "authored_value": source_qty,
            "needed": _GAP_UNCONFIRMED_BASIS,
            "message": (
                f"количество {source_qty:g} не подтверждено источником: в исходном "
                "столбце количества пусто/ошибка/формула без вычисленного значения; "
                "другое число строки за количество не принимается"
            ),
        }
    return None


def _norm_qty_from_visible_row(row: dict[str, Any], code: str, norm: dict[str, Any] | None) -> tuple[float | None, dict[str, Any]]:
    """Keep source quantity; calculate only with GESN scale or a cited conversion."""
    raw_qty, source_unit, raw_qty_text = _quantity_from_visible_row(row)
    base_trace = {
        "source_quantity": raw_qty if raw_qty is not None else raw_qty_text,
        "source_unit": source_unit,
    }
    for field in ("conversion_factor", "calc_quantity"):
        authored = row.get(field)
        if authored is None or str(authored).strip().casefold() in {
            "", "-", "—", "–", "−", "нет", "н/д", "n/a", "na",
        }:
            continue
        parsed = _num(authored)
        if parsed is None or not math.isfinite(parsed):
            return None, {
                **base_trace,
                "status": "needs_input",
                "invalid_field": field,
                "authored_value": authored,
                "message": f"Поле {field} содержит не число: {authored}. Укажите числовое значение; исходный текст сохранён.",
            }
    if raw_qty is None:
        return None, {
            **base_trace,
            "status": "missing_quantity",
            "message": "нет исходного количества для расчёта строки",
        }
    calc = _num(row.get("calc_quantity"))
    factor = _num(row.get("conversion_factor"))
    if calc is not None and factor is not None:
        expected_calc = float(raw_qty) * float(factor)
        if not math.isfinite(expected_calc) or not quantities_close(float(calc), expected_calc):
            return None, {
                **base_trace,
                "status": "needs_input",
                "invalid_field": "calc_quantity",
                "calc_quantity": calc,
                "calc_unit": str(row.get("calc_unit") or "").strip(),
                "conversion_factor": factor,
                "expected_calc_quantity": expected_calc if math.isfinite(expected_calc) else None,
                "conversion_source": str(row.get("conversion_source") or row.get("quantity_source") or "").strip(),
                "message": (
                    "calc_quantity не согласуется с исходным количеством × conversion_factor; "
                    "проверьте оба авторских значения и основание расчёта. Исходные значения сохранены."
                ),
            }
    if norm is None:
        return float(raw_qty), {
            **base_trace,
            "status": "norm_not_found",
            "norm_unit": "",
            "norm_quantity": float(raw_qty),
            "formula": str(raw_qty),
        }

    norm_unit = str(norm.get("unit") or "")
    scale, norm_base_unit = _norm_unit_factor(norm_unit)
    base_trace["norm_measure_factor"] = scale
    cited = _cited_conversion(row, float(raw_qty))
    physical = float(raw_qty)
    extra: dict[str, Any] = {}
    if cited is not None:
        physical, extra = cited
        calc_unit = str(row.get("calc_unit") or "").strip()
        if calc_unit:
            calc_scale, calc_base = norm_measure(calc_unit)
            calc_base = _canon_unit(calc_base)
            extra.update({"calc_unit": calc_unit, "calc_base_unit": calc_base})
            if not math.isfinite(calc_scale) or calc_scale <= 0:
                return None, {
                    **base_trace, **extra, "status": "needs_input", "norm_unit": norm_unit,
                    "invalid_field": "calc_unit",
                    "message": "масштаб расчётной единицы calc_unit должен быть положительным конечным числом",
                }
            extra["calc_measure_factor"] = calc_scale
            si = _unit_conversion_factor(calc_base, norm_base_unit)
            if si is None:
                return None, {
                    **base_trace, **extra, "status": "needs_input", "norm_unit": norm_unit,
                    "invalid_field": "calc_unit",
                    "message": (
                        f"расчётная единица calc_unit {calc_unit!r} несовместима с единицей нормы {norm_unit!r}; "
                        "уточните авторский расчёт, исходные значения сохранены"
                    ),
                }
            physical = float(physical) * calc_scale * si
            extra["si_factor"] = si
    elif not source_unit:
        return None, {
            **base_trace,
            "status": "needs_input",
            "norm_unit": norm_unit,
            "message": "единица исходной строки не указана; код её не угадывает",
        }

    if cited is None:
        source_scale, _source_base = norm_measure(source_unit)
        if not math.isfinite(source_scale) or source_scale <= 0:
            return None, {
                **base_trace, "status": "needs_input", "norm_unit": norm_unit,
                "message": "масштаб исходной единицы должен быть положительным конечным числом",
            }
        physical = float(raw_qty) * source_scale
        if source_scale != 1.0:
            extra["source_measure_factor"] = source_scale

    source_base_unit = _canon_unit(source_unit) if source_unit else norm_base_unit
    if cited is None and source_base_unit != norm_base_unit:
        si = _unit_conversion_factor(source_base_unit, norm_base_unit)
        if si is None:
            return None, {
                **base_trace,
                "status": "needs_input",
                "norm_unit": norm_unit,
                "message": (
                    f"перевод {source_unit!r} → {norm_unit!r} нужен с conversion_factor "
                    "и conversion_source; код не извлекает фасовку или габарит из названия"
                ),
            }
        physical = round(float(physical) * si, 9)
        extra = {**extra, "status": "unit_conversion", "si_factor": si}

    norm_qty = round(float(physical) / float(scale or 1.0), 9)
    if not math.isfinite(norm_qty):
        return None, {
            **base_trace, **extra, "status": "needs_input", "norm_unit": norm_unit,
            "message": "перевод объёма переполняет числовой диапазон; проверьте количество и единицы",
        }
    status = str(extra.get("status") or "")
    if not status:
        status = (
            "direct_norm_quantity"
            if _same_unit_text(source_unit, norm_unit)
            else ("unit_conversion" if scale != 1.0 else "direct_from_row")
        )
    formula = f"{raw_qty} {source_unit}".strip()
    if cited is not None:
        derived = extra.get("calc_quantity")
        if derived is None:
            derived = float(raw_qty) * float(extra["conversion_factor"])
        derivation = f"{raw_qty:g} {source_unit}"
        if extra.get("conversion_factor") is not None:
            derivation += f" × {extra['conversion_factor']:g}"
        formula = (
            f"{derivation} → calc_quantity {derived:g} {extra.get('calc_unit') or norm_base_unit} "
            f"× {extra.get('calc_measure_factor', 1):g} × {extra.get('si_factor', 1):g} "
            f"/ {scale:g} = {norm_qty:g} {norm_unit} ({extra.get('conversion_source')})"
        )
    elif extra.get("source_measure_factor") is not None:
        formula = (
            f"{raw_qty} {source_unit} × {extra['source_measure_factor']:g} "
            f"× {extra.get('si_factor', 1):g} / {scale:g} = {norm_qty}"
        )
    elif extra.get("si_factor") not in (None, 1.0) or scale != 1.0:
        formula = (
            f"{raw_qty} {source_unit} × {extra.get('si_factor', 1):g} "
            f"/ {scale:g} = {norm_qty}"
        )
    return norm_qty, {
        **base_trace,
        **extra,
        "status": status,
        "norm_unit": norm_unit,
        "norm_quantity": norm_qty,
        "formula": formula,
    }


def _with_visible_identity(
    binding: dict[str, Any],
    *,
    title: str,
    source_qty: Any,
    source_unit: str,
) -> dict[str, Any]:
    """Keep the operator-visible VOR line on every bind/skip record."""

    if title:
        binding.setdefault("name", title)
        binding.setdefault("title", title)
    if source_qty is not None:
        binding.setdefault("source_quantity", source_qty)
    if source_unit:
        binding.setdefault("source_unit", source_unit)
    return binding


_SUBSTANTIATED_NORM_STATUSES = {
    "EXACT",
    "ANALOGUE",
    "ANALOGUE_CANDIDATE",
    "EXACT_VERIFIED",
    "ANALOGUE_VERIFIED",
}

def source_confirmed_zero_work_charge_not_required(
    row: Mapping[str, Any], source_catalog: AttachmentSourceCatalog | None,
) -> bool:
    """An exact numeric source-confirmed zero creates no charge or norm decision."""
    if inferred_row_role(row) != "work" or _code_from_visible_row(row) or source_catalog is None:
        return False
    if not source_catalog.extraction_complete:
        return False
    # Do not erase an authored recalculation, quote, resource action or coverage
    # relation. They keep their existing validation path even when raw qty is 0.
    for field in ("calc_quantity", "conversion_factor", "calc_unit", "conversion_source",
                  "quantity_source", "confirmed_price", "resource_bindings", "resource_review",
                  "covered_by_work_id", "covered_by_operation_id"):
        if row.get(field) not in (None, "", [], {}):
            return False
    components = row.get("norm_components")
    if not (components is None or components == "" or (isinstance(components, list) and not components)):
        return False
    quantity = _first_value(row, "qty", "quantity", "quantity_total", "volume", "amount_qty",
                            "количество", "кол-во", "объем", "объём")
    if isinstance(quantity, str):
        literal = quantity.strip()
        if re.fullmatch(r"[+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)(?:[eE][+-]?[0-9]+)?", literal) is None:
            return False
        try:
            exact_quantity = Decimal(literal.replace(",", "."))
        except InvalidOperation:
            return False
        # Float underflow must never make an exact nonzero decimal a zero.
        if not exact_quantity.is_finite() or not exact_quantity.is_zero():
            return False
    elif type(quantity) not in (int, float) or not math.isfinite(quantity) or quantity != 0:
        return False
    return bool(source_confirms_literal_zero_quantity(source_catalog, row.get("source_row"))
                and not compare_model_row_to_catalog(row, source_catalog))


def _row_readiness(binding: dict[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    """Per-row split of the §6 states — never raised above what the data shows.

    Code reports facts only: was the row given an explicit role, does a cipher
    exist, did the model substantiate applicability, was the volume verified,
    is a position calculated, are all amounts priced. ``bound`` alone is none
    of "fully ready" or "price found".
    """

    role = str(binding.get("row_role") or "") or canonicalize_row_role(
        row.get("row_role")
    ) or inferred_row_role(row)
    status = str(binding.get("status") or "")
    explicit_header = (
        canonicalize_row_role(row.get("row_role")) == "header" or role == "header"
    )
    operation_defined = (
        explicit_header
        or role in {"work", "material", "equipment", "resource"}
        or (role == "unresolved" and bool(str(row.get("open_gap") or row.get("open_question") or "").strip()))
    )
    no_charge = binding.get("charge_not_required") is True
    if no_charge:
        norm_selected = None
    elif str(binding.get("code") or ""):
        norm_selected = True
    elif (
        explicit_header
        or (role in {"material", "equipment"} and status == "bound")
        # § 4: a resource line is priced inside its work and selects no mounting
        # norm of its own, so «нет» here would be a defect the row cannot answer.
        or role == "resource"
    ):
        norm_selected = None  # a heading, supply or resource line takes no mounting norm
    else:
        norm_selected = False
    authored_status = str(binding.get("norm_status") or "") or (
        str(row.get("norm_status") or "").strip().upper() if norm_selected else ""
    )
    # ADR-16 § 6: the status token is the model's claim, never the evidence for
    # it.  A cipher that no cited card carries, or an analogue whose five match
    # fields the model left unproven, stays a candidate: it may show in the
    # draft and in the trace, but it does not make the row applicable.
    if norm_selected is None:
        # Task 2026-09-29 § 4: a heading or a supply line has no mounting decision
        # to substantiate, so the honest answer is "the question does not apply",
        # not "нет" — the sheet must not print an absent question as a defect.
        applicability: Any = None
    else:
        applicability = bool(norm_selected) and (
            authored_status in _SUBSTANTIATED_NORM_STATUSES
        ) and not binding.get("action_conflict") and norm_applicability_substantiated(
            {
                **dict(row),
                "norm_status": authored_status,
                "norm_code": str(binding.get("code") or row.get("norm_code") or ""),
            }
        )
    if no_charge:
        volume_verified = True
    elif role in {"material", "equipment"} and status not in {
        "unconfirmed_quantity", "missing_quantity",
    }:
        volume_verified: bool | None = True
    elif status in {"unconfirmed_quantity", "missing_quantity"}:
        volume_verified = False
    elif isinstance(binding.get("quantity_trace"), Mapping):
        volume_verified = status not in {"needs_input", "norm_not_found"}
    elif status == "bound":
        volume_verified = True
    else:
        volume_verified = None
    return {
        "source_accounted": True,
        "operation_defined": operation_defined,
        "norm_selected": norm_selected,
        "applicability_substantiated": applicability,
        "volume_verified": volume_verified,
        # § 4: the calculation questions belong to a row that owns a position.  A
        # heading or a resource line has none of its own, so its answer is «н/п» —
        # not the «нет» that would count it as an unfinished calculation.
        "position_calculated": (
            bool(binding.get("position")) if role not in {"header", "resource"} and not no_charge else None
        ),
        "prices_provided": None,
        # Task 2026-09-29 § 4: the seven questions of one operation, kept apart
        # because each has its own answer.  "The structure is built" says the
        # resources, units and accruals of the position are accounted; "an amount
        # is known" says at least part of its money is; "the position is fully
        # calculated" needs both plus owned prices.  The readiness loop fills them
        # from the calculator's own completeness reasons, and a row with no
        # position (a heading) keeps them as "not applicable".
        "structure_calculated": None,
        "known_amount_present": None,
        "row_role": role,
        "header_row": explicit_header,
    }


def positions_from_visible_lsr_rows(
    rows: list[dict[str, Any]], *, source_catalog: AttachmentSourceCatalog | None = None,
) -> dict[str, Any]:
    """Bind already visible/selected LSR rows to trace positions.

    This function does not search or select norms and does not require an
    independent EXACT_VERIFIED overlay. An explicit model cipher goes to exact
    lookup and quantity conversion. MISSING/CONFLICT, unknown codes, and unit
    failures stay unbound. A named NEEDS_RESEARCH cipher is calculated when the
    card exists, stays marked as analogue, and never becomes priced_final.
    """
    positions: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    coverage_links = resolve_work_coverage(rows or [], source_catalog=source_catalog)
    supplies_by_parent: dict[str, list[Mapping[str, Any]]] = {}
    work_ids_by_parent: dict[str, set[str]] = {}
    work_indices_by_alias: dict[str, set[int]] = {}
    linked_resources_by_work: dict[int, list[Mapping[str, Any]]] = {}
    resource_link_errors: dict[int, str] = {}

    def parent_key(value: Any) -> str:
        return catalog_source_locator(value, source_catalog)

    for index, item in enumerate(rows or []):
        if inferred_row_role(item) == "work":
            for key in {str(item.get("source_row") or ""), parent_key(item.get("source_row")),
                        str(item.get("operation_id") or ""),
                        operation_identity(item)} - {""}:
                work_indices_by_alias.setdefault(key, set()).add(index)
    for index, item in enumerate(rows or []):
        if inferred_row_role(item) == "resource" and ("resource_bindings" in item or "resource_review" in item):
            parent = work_row_key(item)
            targets = work_indices_by_alias.get(parent, set()) | work_indices_by_alias.get(parent_key(parent), set())
            if len(targets) == 1:
                linked_resources_by_work.setdefault(next(iter(targets)), []).append(item)
            else:
                resource_link_errors[index] = "Конфликт связи действия над ресурсом: работа не найдена или адрес неоднозначен."
    for item in rows or []:
        role = inferred_row_role(item)
        parent = work_row_key(item)
        if role == "work":
            for key in {parent_key(item.get("source_row")), parent_key(parent),
                        str(item.get("operation_id") or ""), operation_identity(item)} - {""}:
                work_ids_by_parent.setdefault(key, set()).add(operation_identity(item))
        elif role in {"material", "equipment"} and parent:
            if (canonicalize_supply_kind(item.get("supply_kind")) or "supply") in {"supply", "both"}:
                supplies_by_parent.setdefault(parent_key(parent), []).append(item)
    for idx, row in enumerate(rows or [], 1):
        model_source_row = row.get("source_row")
        source_row = (
            model_source_row
            if (
                isinstance(model_source_row, int)
                and not isinstance(model_source_row, bool)
                and model_source_row > 0
            )
            or (isinstance(model_source_row, str) and bool(model_source_row.strip()))
            else idx
        )
        code = _code_from_visible_row(row)
        title = str(_first_value(row, "title", "name", "work", "наименование", "работа") or "")
        source_qty, source_unit, raw_qty_text = _quantity_from_visible_row(row)
        model_status = (
            canonicalize_norm_status(row.get("norm_status"))
            if row.get("norm_status") not in (None, "")
            else ""
        )
        role = inferred_row_role(row)
        parent = work_row_key(row)
        if idx - 1 in coverage_links:
            link = coverage_links[idx - 1]
            error = str(link.get("error") or "")
            if not error and not str(row.get("coverage") or "").strip():
                error = "coverage_basis_missing"
            if not error and not _visible_row_has_evidence(row):
                error = "coverage_evidence_missing"
            if not error and (model_status in {"CONFLICT", "MISSING", "NEEDS_RESEARCH"}
                              or applicability_gap_kind(row)
                              or (isinstance(row.get("_evidence_check"), Mapping)
                                  and row["_evidence_check"].get("card_body_shown") is False)):
                error = "coverage_basis_unresolved"
            gap = _unconfirmed_source_change(row, source_qty=source_qty, source_unit=source_unit)
            if not error and (gap is not None or source_qty is None):
                error = "coverage_quantity_conflict"
            binding = {
                "row": source_row, "code": code, "norm_status": model_status,
                "status": "coverage_conflict" if error else "coverage_pending",
                "row_role": role, "source_row": row,
                "coverage_error": error,
                "coverage_reason": str(row.get("coverage") or ""),
                "coverage_target_index": link.get("target_index"),
                "coverage_direct_target_index": link.get("direct_target_index"),
                "message": _coverage_message(error),
            }
            bindings.append(_with_visible_identity(
                binding, title=title, source_qty=source_qty, source_unit=source_unit))
            continue
        if role in {"material", "equipment", "header"} and code:
            # A mounting norm cannot become a supply price just because the
            # model wrote its cipher on an explicit non-work row. Preserve the
            # authored role/code and expose the type conflict; never reclassify.
            bindings.append(_with_visible_identity(
                {"row": source_row, "code": code, "status": "role_norm_conflict",
                 "row_role": role, "work_row": parent, "source_row": row,
                 "message": "Монтажная норма указана на строке поставки или заголовке; уточните роль операции и связь с работой."},
                title=title, source_qty=source_qty, source_unit=source_unit))
            continue
        if canonicalize_row_role(row.get("row_role")) == "header" and not code:
            # Headings/notes/subtotals are accounted as structure — no norm,
            # no volume gate, and no place in any sum.
            bindings.append(
                _with_visible_identity(
                    {
                        "row": source_row,
                        "status": "structure_accounted",
                        "row_role": "header",
                        "message": "структурная строка исходника учтена без монтажной нормы",
                        "source_row": row,
                    },
                    title=title,
                    source_qty=source_qty,
                    source_unit=source_unit,
                )
            )
            continue
        if role == "resource":
            binding = {
                "row": source_row,
                "status": "resource_linked",
                "row_role": role,
                "work_row": parent,
                "message": "ресурс отнесён к работе по locator, не по шифру",
                "source_row": row,
            }
            if code:
                binding["code"] = code
            if idx - 1 in resource_link_errors:
                binding.update(status="resource_link_conflict", message=resource_link_errors[idx - 1],
                               resource_bindings=row.get("resource_bindings"))
            bindings.append(
                _with_visible_identity(
                    binding, title=title, source_qty=source_qty, source_unit=source_unit
                )
            )
            continue
        gap = _unconfirmed_source_change(
            row, source_qty=source_qty, source_unit=source_unit
        )
        if gap is not None:
            bindings.append(
                _with_visible_identity(
                    {
                        "row": source_row,
                        "status": "unconfirmed_quantity",
                        "row_role": role,
                        "work_row": parent,
                        "message": gap["message"],
                        "quantity_gap": gap,
                        "source_row": row,
                    },
                    title=title,
                    source_qty=source_qty,
                    source_unit=source_unit,
                )
            )
            continue
        if source_confirmed_zero_work_charge_not_required(row, source_catalog):
            message = "Подтверждённый исходником объём 0; начисление не требуется."
            bindings.append(_with_visible_identity(
                {"row": source_row, "status": "bound", "row_role": role,
                 "work_row": parent, "source_row": row, "charge_not_required": True,
                 "message": message, "reason": message},
                title=title, source_qty=source_qty, source_unit=source_unit))
            continue
        if role in {"material", "equipment"} and not code:
            price = _num(row.get("confirmed_price"))
            if price is not None and not math.isfinite(price):
                price = None
            resource = {
                "kind": "material",
                "name": title,
                "code": str(row.get("resource_code") or ""),
                "unit": source_unit,
                "per_unit": 1,
                "requires_kac_provenance": True,
                "requires_price_unit_provenance": True,
                "price_origin": "model_result",
            }
            price_unit = str(row.get("price_unit") or "").strip()
            if price_unit:
                resource["price_unit"] = price_unit
            price_source, price_owner = _visible_price_owner(row)
            if price is not None:
                resource["price"] = price
                if price_source:
                    resource["price_source_ref"] = price_source
            if source_qty is None:
                bindings.append(
                    _with_visible_identity(
                        {
                            "row": source_row,
                            "status": "missing_quantity",
                            "row_role": role,
                            "work_row": parent,
                            "message": (
                                "материал без количества: код не подставляет 1, "
                                "нужно исходное количество из строки"
                            ),
                            "source_row": row,
                        },
                        title=title,
                        source_qty=source_qty,
                        source_unit=source_unit,
                    )
                )
                continue
            position = {
                "code": "",
                "op_key": operation_identity(row),
                "qty": float(source_qty),
                "name": title,
                "unit": source_unit,
                "section": str(_first_value(row, "section", "раздел") or "").strip() or "Без раздела",
                "source_row": source_row,
                "work_row": parent,
                "row_role": role,
                "supply_kind": str(row.get("supply_kind") or "supply"),
                "resources": [resource],
                "nr_pct": 0,
                "sp_pct": 0,
                "source_quantity": source_qty,
                "source_unit": source_unit,
            }
            if price is not None and price_unit and book_price_unit_conflict(price_unit, source_unit):
                price_qty, price_qty_trace = _norm_qty_from_visible_row(row, "", {"unit": price_unit})
                resource["price_quantity_trace"] = price_qty_trace
                if price_qty is not None:
                    # A supply has no normative target unit: its own declared
                    # quote is the conversion target. Keep the source unchanged.
                    position.update(qty=price_qty, unit=price_unit, quantity_trace=price_qty_trace)
                    resource["unit"] = price_unit
            refs = _normalize_evidence_refs(_first_value(row, "evidence_refs", "source_refs"))
            if refs:
                position["evidence_refs"] = refs
            position["resource_selection_unsubstantiated"] = (
                bool(resource["code"]) and (
                    (not _visible_row_has_evidence(row) and price_owner != "operator")
                    or (
                        "_resource_evidence_check" in row and (
                            not isinstance(row["_resource_evidence_check"], Mapping)
                            or row["_resource_evidence_check"].get("code_in_refs") is not True
                        )
                    )
                )
            )
            from proxy.services.model_resource_binding_service import supply_resource_match_substantiated

            # An operator quantity/unit edit also stamps confirmed_by. Only an
            # actual owned price (including zero) confirms the monetary choice.
            operator_price_confirmed = price_owner == "operator" and price is not None
            position["supply_resource_match_unsubstantiated"] = (
                bool(resource["code"]) and not operator_price_confirmed
                and not supply_resource_match_substantiated(row)
            )
            position["supply_price_kind_conflict"] = (
                "price_kind" in row and str(row.get("price_kind") or "").strip() != "unit_price"
                and price_owner != "operator"
            )
            if "norm_components" in row:
                position["norm_components"] = deepcopy(row["norm_components"])
            positions.append(position)
            bindings.append(
                _with_visible_identity(
                    {
                        "row": source_row,
                        "status": "bound",
                        "row_role": role,
                        "work_row": parent,
                        "source_row": row,
                        "position": {k: v for k, v in position.items() if k != "source_row"},
                    },
                    title=title,
                    source_qty=source_qty,
                    source_unit=source_unit,
                )
            )
            continue
        named_research = model_status == "NEEDS_RESEARCH" and bool(code)
        if (
            model_status in {"MISSING", "CONFLICT"}
            or role == "unresolved"
            or (model_status == "NEEDS_RESEARCH" and not named_research)
        ):
            status = {
                "MISSING": "missing_norm",
                "NEEDS_RESEARCH": "needs_research",
                "CONFLICT": "quality_conflict",
            }.get(model_status, "unresolved")
            message = str(
                row.get("open_gap") or row.get("open_question")
                or row.get("quality_message")
                or f"модель оставила строку в статусе {model_status or role}"
            )
            binding = {
                "row": source_row,
                "status": status,
                "row_role": role,
                "message": message,
                "coverage_reason": message,
                "norm_status": model_status,
                "quality_gate": str(row.get("_quality_gate") or ""),
                "source_row": row,
            }
            if code:
                binding["code"] = code
            if source_qty is not None:
                binding["source_quantity"] = source_qty
            if source_unit:
                binding["source_unit"] = source_unit
            bindings.append(
                _with_visible_identity(
                    binding, title=title, source_qty=source_qty, source_unit=source_unit
                )
            )
            continue
        if not code:
            binding = {
                "row": source_row,
                "status": "norm_selection_required",
                "message": "в строке нет шифра нормы",
                "source_row": row,
            }
            if source_qty is not None:
                binding["source_quantity"] = source_qty
            if source_unit:
                binding["source_unit"] = source_unit
            bindings.append(
                _with_visible_identity(
                    binding, title=title, source_qty=source_qty, source_unit=source_unit
                )
            )
            continue
        evidence_check = row.get("_evidence_check")
        application_bound = isinstance(evidence_check, Mapping)
        evidence_check = evidence_check if application_bound else {}
        norm_key = qualified_norm_key(code)
        expected_key = str(evidence_check.get("norm_key") or "")
        expected_norm_key = qualified_norm_key(expected_key)
        expected_sha = str(evidence_check.get("normative_base_sha256") or "")
        identity_conflict = not norm_key or (expected_norm_key and expected_norm_key != norm_key)
        generation_unconfirmed = application_bound and (
            not expected_norm_key or not re.fullmatch(r"[0-9a-f]{64}", expected_sha)
        )
        snapshot_conflict = evidence_check.get("normative_snapshot_conflict")
        norm = None
        snapshot_error = ""
        generation_reason = ""
        if identity_conflict:
            conflict_status = "norm_identity_conflict"
            conflict_message = "шифр не определяет полное семейство и элемент нормы; авторский выбор сохранён"
        elif snapshot_conflict:
            conflict_status = "normative_generation_conflict"
            conflict_message = "приведённые карточки не определяют единое поколение нормы; расчёт не выполнен"
            generation_reason = "cited_normative_generations_conflict"
        elif generation_unconfirmed:
            conflict_status = "normative_generation_conflict"
            conflict_message = "поколение процитированной нормы не подтверждено полным ключом и SHA-256; авторский выбор сохранён"
            generation_reason = "cited_normative_generation_unconfirmed"
        else:
            try:
                norm = gesn_service.get_norm(code, expected_base_sha256=expected_sha) if expected_sha else gesn_service.get_norm(code)
            except gesn_service.NormativeSnapshotConflict as error:
                snapshot_error = str(error)
            conflict_status = "normative_generation_conflict" if snapshot_error else ""
            conflict_message = "поколение нормы из карточки не воспроизведено для расчёта; авторский выбор сохранён"
            generation_reason = "cited_normative_generation_mismatch" if snapshot_error else ""
        if conflict_status:
            binding = {
                "row": source_row, "code": code, "status": conflict_status,
                "message": conflict_message, "row_role": role,
                "norm_status": model_status, "source_row": row,
            }
            if snapshot_error:
                binding["normative_snapshot_error"] = snapshot_error
            if generation_reason:
                binding["normative_generation_reason"] = generation_reason
            if source_qty is not None:
                binding["source_quantity"] = source_qty
            if source_unit:
                binding["source_unit"] = source_unit
            bindings.append(_with_visible_identity(
                binding, title=title, source_qty=source_qty, source_unit=source_unit
            ))
            continue
        if norm is None:
            binding = {
                "row": source_row,
                "code": code,
                "status": "norm_not_found",
                "message": "шифр нормы не найден в нормативной базе",
                "source_row": row,
            }
            if source_qty is not None:
                binding["source_quantity"] = source_qty
            if source_unit:
                binding["source_unit"] = source_unit
            bindings.append(
                _with_visible_identity(
                    binding, title=title, source_qty=source_qty, source_unit=source_unit
                )
            )
            continue
        norm_qty, qty_trace = _norm_qty_from_visible_row(row, code, norm)
        # ADR-16 § 6: a reversal between the row's own words and the card's own
        # words is recorded whether or not the volume could be resolved, so the
        # row is never reported as merely "waiting for a number".
        action_conflict = norm_action_conflict(title, norm)
        if norm_qty is None:
            binding = {
                "row": source_row,
                "code": code,
                "status": qty_trace.get("status") or "needs_input",
                "quantity_trace": qty_trace,
                "source_row": row,
            }
            if action_conflict:
                binding["action_conflict"] = action_conflict
            if source_qty is not None:
                binding["source_quantity"] = source_qty
            if source_unit:
                binding["source_unit"] = source_unit
            bindings.append(
                _with_visible_identity(
                    binding, title=title, source_qty=source_qty, source_unit=source_unit
                )
            )
            continue
        position = {
            "code": code,
            "op_key": operation_identity(row),
            "qty": norm_qty,
            "section": str(_first_value(row, "section", "раздел") or "").strip() or "Без раздела",
            "source_row": source_row,
            "quantity_trace": qty_trace,
            "source_quantity": source_qty,
            "source_unit": source_unit,
            "norm_quantity": norm_qty,
            "_norm_snapshot": deepcopy(norm),
        }
        if title:
            position["name"] = title
        if action_conflict:
            position["action_conflict"] = action_conflict
        confirmed_price = _num(row.get("confirmed_price"))
        if confirmed_price is not None and math.isfinite(confirmed_price):
            price_source, price_owner = _visible_price_owner(row)
            position["confirmed_price"] = confirmed_price
            position["price_source"] = price_source
            position["confirmed_price_attributed"] = bool(price_source)
            position["price_owner"] = price_owner
            if price_owner != "operator" or str(row.get("price_kind") or "").strip() in {"unit_price", "position_total"}:
                price_kind = str(row.get("price_kind") or "").strip()
                price_unit = str(_first_value(row, "price_unit", "unit") or "").strip()
                position["confirmed_price_kind"] = price_kind
                position["confirmed_price_quantity"] = source_qty
                position["confirmed_price_unit"] = price_unit
                if price_kind not in {"position_total", "unit_price"}:
                    position["confirmed_price_attributed"] = False
                    position["confirmed_price_issue"] = "position_price_kind_unknown"
                elif price_kind == "unit_price" and book_price_unit_conflict(price_unit, source_unit):
                    conversion_row = row
                    price_base = _norm_unit_factor(price_unit)[1]
                    source_base = _norm_unit_factor(source_unit)[1]
                    calc_unit = str(row.get("calc_unit") or "").strip()
                    calc_to_quote = bool(calc_unit) and _unit_conversion_factor(
                        _norm_unit_factor(calc_unit)[1], price_base,
                    ) is not None
                    if (
                        _unit_conversion_factor(source_base, price_base) is not None
                        or (price_base != _norm_unit_factor((norm or {}).get("unit"))[1] and not calc_to_quote)
                    ):
                        # A whole-work unit quote prices the physical source
                        # volume, not repeated norm equivalents. Cross-dimensional
                        # conversion still needs its authored basis in the quote's
                        # unit; an unrelated norm conversion cannot become one.
                        conversion_row = {key: value for key, value in row.items()
                                          if key not in {"calc_quantity", "calc_unit", "conversion_factor", "conversion_source", "quantity_source"}}
                    price_qty, price_qty_trace = _norm_qty_from_visible_row(conversion_row, "", {"unit": price_unit})
                    position["confirmed_price_quantity"] = price_qty
                    position["confirmed_price_quantity_trace"] = price_qty_trace
                    if price_qty is None:
                        position["confirmed_price_attributed"] = False
                        position["confirmed_price_issue"] = "position_price_unit_conflict"
        if norm and norm.get("unit"):
            position["unit"] = norm.get("unit")
        position["row_role"] = role
        position["work_row"] = parent or str(source_row)
        if isinstance(row.get("_evidence_check"), Mapping) and row["_evidence_check"].get("card_body_shown") is False:
            position["norm_card_body_unread"] = True
        analogue = str(_first_value(row, "analogue", "coverage") or "").strip()
        if analogue:
            position["analogue"] = analogue
            position["coverage"] = analogue
        refs = row.get("evidence_refs")
        if refs:
            position["evidence_refs"] = list(refs) if isinstance(refs, list) else [refs]
        if row.get("nr_sp_rule_id") not in (None, ""):
            # Carry the authored choice; resolve() rejects foreign collection IDs.
            # Missing/ambiguous rules remain open, never a title-based default.
            position["nr_sp_rule_id"] = row["nr_sp_rule_id"]
        position.update(_model_coefficient_fields(row))
        linked_supply_rows = [supply for key in {parent_key(source_row), parent_key(parent),
                                               str(row.get("operation_id") or ""), operation_identity(row)} - {""}
                              for supply in supplies_by_parent.get(key, [])]
        linked_resource_rows = linked_resources_by_work.get(idx - 1, [])
        rejected_resource_rows = [owner for owner in linked_resource_rows
                                  if _code_from_visible_row(owner) and _code_from_visible_row(owner) != code]
        linked_resource_rows = [owner for owner in linked_resource_rows if owner not in rejected_resource_rows]
        if "resource_bindings" in row or "resource_review" in row or linked_supply_rows or linked_resource_rows:
            from proxy.services.model_resource_binding_service import resource_binding_position_fields
            from proxy.smeta_core.resource_normalizer import normalize_norm_resources

            position.update(resource_binding_position_fields(
                row,
                [_plain_resource_line(dict(resource)) for resource in normalize_norm_resources(list(norm.get("resources") or []))],
                work_id=operation_identity(row), work_qty=norm_qty,
                physical_quantity=source_qty, physical_unit=source_unit,
                linked_supply_rows=linked_supply_rows,
                linked_resource_rows=linked_resource_rows,
                supply_parent_ambiguous=any(len(work_ids_by_parent.get(parent_key(work_row_key(supply)), set())) != 1
                                            for supply in linked_supply_rows),
            ))
        if rejected_resource_rows:
            position.setdefault("resource_binding_conflicts", []).extend({
                "code": "resource_binding_conflict", "work_id": operation_identity(row),
                "reason": "linked resource norm disagrees with its work", "source_row": owner.get("source_row"),
                "proposal": dict(owner),
            } for owner in rejected_resource_rows)
        if (
            position.get("coefficient_application") == "applied"
            and (
                float(position.get("k_ozp") or 1.0) != 1.0
                or float(position.get("k_em") or 1.0) != 1.0
            )
            and _visible_row_quantity_already_includes_coefficient(
                row,
                title=title,
                raw_qty_text=raw_qty_text,
            )
        ):
            position["source_coefficient_overlap"] = True
        if "norm_components" in row:
            position["norm_components"] = deepcopy(row["norm_components"])
        positions.append(position)
        binding: dict[str, Any] = {
            "row": source_row,
            "code": code,
            "status": "bound",
            "quantity_trace": qty_trace,
            "source_row": row,
            "position": {k: v for k, v in position.items() if k != "source_row"},
        }
        for key in (
            "coefficient",
            "coefficient_value",
            "coefficient_applies_to",
            "coefficient_application",
            "evidence_refs",
            "source_quantity",
            "source_unit",
            "norm_quantity",
            "source_coefficient_overlap",
            "action_conflict",
            "resource_bindings",
            "resource_review",
            "separate_supply_review_audit",
            "resource_binding_audit",
            "resource_binding_conflicts",
        ):
            if key in position:
                binding[key] = position[key]
        binding["norm_status"] = model_status or "MODEL_SELECTED"
        binding["quality_gate"] = str(row.get("_quality_gate") or "not_run")
        if model_status == "NEEDS_RESEARCH":
            reason = str(
                row.get("open_gap")
                or row.get("open_question")
                or row.get("quality_message")
                or "модель оставила шифр как аналог / NEEDS_RESEARCH"
            )
            binding["selection_kind"] = binding.get("selection_kind") or "analogue"
            binding["coverage_reason"] = reason
            binding["message"] = reason
            position.setdefault("analogue", reason)
        bindings.append(
            _with_visible_identity(
                binding, title=title, source_qty=source_qty, source_unit=source_unit
            )
        )
    # Resolve after every independently billed operation has been constructed.
    # A link never manufactures a position or a norm for its target.
    for binding in bindings:
        if binding.get("status") != "coverage_pending":
            continue
        ancestor = bindings[binding["coverage_direct_target_index"]]
        while ancestor.get("status") in {"coverage_pending", "covered"}:
            ancestor = bindings[ancestor["coverage_direct_target_index"]]
        if ancestor.get("status") == "coverage_conflict":
            binding.update(status="coverage_conflict", coverage_error="coverage_target_unbound",
                           message=_coverage_message("coverage_target_unbound"))
            continue
        target = bindings[binding["coverage_target_index"]]
        if target.get("status") != "bound":
            binding.update(status="coverage_conflict", coverage_error="coverage_target_unbound",
                           message=_coverage_message("coverage_target_unbound"))
            continue
        binding.update(status="covered", covered_by_work_id=str(target["row"]),
                       covered_by_operation_id=operation_identity(target["source_row"]),
                       message=f"Учтено в работе {target['row']}; повторно не начисляется. "
                               + binding["coverage_reason"])
    return {"positions": positions, "row_bindings": bindings}


def _coverage_message(error: str) -> str:
    return {
        "coverage_target_invalid": "Связь учтённой работы должна быть адресом строки или operation_id.",
        "coverage_target_missing": "Работа, в которой учтена строка, не найдена.",
        "coverage_target_ambiguous": "По адресу несколько работ; укажите operation_id нужной операции.",
        "coverage_role_conflict": "Связь полного учёта допускается только между работами.",
        "coverage_cycle": "Обнаружена циклическая ссылка между учтёнными работами.",
        "coverage_basis_missing": "Не приведено обоснование полного учёта работы в coverage.",
        "coverage_evidence_missing": "Нет разрешаемой ссылки на источник, обосновывающий учёт работы.",
        "coverage_basis_unresolved": "Модель оставила противоречие или неподтверждённую применимость основания учёта.",
        "coverage_quantity_conflict": "Объём учтённой работы расходится с исходником без основания.",
        "coverage_target_unbound": "Связанная работа не включена в расчёт; её пробел требуется закрыть.",
    }.get(error, "Проверка ссылки на работу, в которой учтена строка.")


_SELECTED_CIPHER_RE = re.compile(
    r"(?:ГЭСН|ФЕР|ТЕР|GESN|FER|TER)(?:мр|м|п|р)?[:\s]*"
    r"\d{1,3}[-–]\d{1,2}[-–]\d{1,3}[-–]\d{1,2}[а-яa-z]?"
    r"|\d{1,3}[-–]\d{1,2}[-–]\d{1,3}[-–]\d{1,2}[а-яa-z]?",
    re.IGNORECASE,
)


def _is_selected_cipher(value: Any) -> bool:
    """A real cipher cell only: '-', MISSING and explanations are not norms."""

    text = str(value or "").strip().strip("`* ")
    return bool(text) and bool(_SELECTED_CIPHER_RE.fullmatch(text))


def build_lsr_trace_from_visible_rows(
    rows: list[dict[str, Any]],
    *,
    source_catalog: AttachmentSourceCatalog | None = None,
    pricebook=None,
    kac_map: dict[str, float] | None = None,
    k_ozp: float = 1.0,
    k_em: float = 1.0,
    coefficient_basis: str = "",
    name: str = "",
    confirmed_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Visible/BOR/LSR rows with selected norm codes -> priced_partial/final RIM trace."""
    visible = apply_confirmed_data(rows, confirmed_data)
    bound = positions_from_visible_lsr_rows(visible, source_catalog=source_catalog)
    lsr = build_lsr_trace(
        bound["positions"],
        pricebook=pricebook,
        kac_map=kac_map,
        k_ozp=k_ozp,
        k_em=k_em,
        coefficient_basis=coefficient_basis,
        name=name,
    )
    closed = {"bound", "covered", "resource_linked", "structure_accounted"}
    binding_flags = [
        f"строка {b.get('row')}: {b.get('message') or b.get('status')}"
        for b in bound["row_bindings"]
        if b.get("status") not in closed
    ]
    summary = lsr.setdefault("summary", {})
    summary["input_rows"] = len(rows or [])
    summary["bound_rows"] = len(bound["positions"])
    summary["covered_rows"] = sum(b.get("status") == "covered" for b in bound["row_bindings"])
    summary["charge_not_required_rows"] = sum(item.get("charge_not_required") is True for item in bound["row_bindings"])
    summary["unbound_rows"] = max(0, len(rows or []) - len(bound["positions"]) - summary["charge_not_required_rows"])
    open_bindings = [
        item for item in bound["row_bindings"] if item.get("status") not in closed
    ]
    research_priced = [
        item
        for item in bound["row_bindings"]
        if item.get("status") == "bound"
        and canonicalize_norm_status(item.get("norm_status")) == "NEEDS_RESEARCH"
    ]
    if bound["positions"] and not open_bindings and not research_priced:
        summary["norms_status"] = "model_norms_selected"
    elif bound["positions"]:
        summary["norms_status"] = "model_norms_partial"
    else:
        summary["norms_status"] = "norm_selection_required"
    if binding_flags:
        summary["flags"] = list(summary.get("flags") or []) + binding_flags
    if research_priced:
        summary["flags"] = list(summary.get("flags") or []) + [
            f"строка {item.get('row')}: analog {item.get('code') or ''} "
            "посчитан, статус NEEDS_RESEARCH сохранён".strip()
            for item in research_priced
        ]
    no_charge_only = any(item.get("charge_not_required") is True for item in bound["row_bindings"]) and all(
        item.get("charge_not_required") is True or item.get("status") == "structure_accounted"
        for item in bound["row_bindings"])
    if no_charge_only:
        summary.update(result_status="priced_final", amount_status="complete", full_amount=0.0)
    elif not bound["positions"]:
        summary["result_status"] = "norm_selection_required"
    elif gap_flags(summary.get("flags") or []):
        summary["result_status"] = "priced_partial"
    else:
        summary["result_status"] = "priced_final"
    visible_by_row = {item.get("source_row"): item for item in visible}
    amounts_by_op: dict[str, dict[str, Any]] = {}
    amounts_by_row: dict[Any, dict[str, Any]] = {}
    numbers_by_op: dict[str, int] = {}
    numbers_by_row: dict[Any, int] = {}
    # § 4: how many operations the revision built on one source row — a locator that
    # carries two is not one finished position, and the sheet has to show both.
    operations_per_locator: dict[Any, int] = {}
    for entry in lsr.get("sections") or []:
        for trace in entry.get("positions") or []:
            pos_summary = trace.get("summary") or {}
            op_key = str(trace.get("op_key") or "")
            if op_key:
                amounts_by_op[op_key] = pos_summary
                if trace.get("position_no") is not None:
                    numbers_by_op[op_key] = int(trace["position_no"])
            if trace.get("source_row") is not None:
                amounts_by_row.setdefault(trace.get("source_row"), pos_summary)
                if trace.get("position_no") is not None:
                    numbers_by_row.setdefault(trace.get("source_row"), int(trace["position_no"]))
                operations_per_locator[trace.get("source_row")] = (
                    operations_per_locator.get(trace.get("source_row"), 0) + 1
                )
    conflict_locators = {
        str(item.get("locator") or "") for item in double_count_conflicts(visible)
    }
    kind_counts = {"work": 0, "material": 0, "equipment": 0, "resource": 0, "header": 0, "unresolved": 0}
    selected_norms = 0
    selected_ciphers: set[str] = set()
    calculated_positions = 0
    confirmed_amount = 0.0
    preliminary_amount = 0.0
    has_preliminary_positions = False
    for binding in bound["row_bindings"]:
        source_row = binding.get("row")
        model_row = binding.get("source_row")
        if not isinstance(model_row, Mapping):
            model_row = visible_by_row.get(source_row) or {}
        readiness = _row_readiness(binding, model_row)
        position = binding.get("position")
        if isinstance(position, Mapping):
            op_key = str(position.get("op_key") or "")
            pos_summary = (
                amounts_by_op.get(op_key)
                or amounts_by_row.get(source_row)
                or {}
            )
            # § 4: the position number the delivered document prints, and how many
            # operations the revision built on this one source row.
            position_number = numbers_by_op.get(op_key) or numbers_by_row.get(source_row)
            if position_number is not None:
                binding["position_no"] = int(position_number)
            binding["locator_operations"] = int(
                operations_per_locator.get(source_row) or 1
            )
            amount = _f(pos_summary.get("known_amount", pos_summary.get("total")))
            complete = pos_summary.get("amount_status") == "complete" and pos_summary.get("full_amount") is not None
            _opt = pos_summary.get("operator_price_trace") or {}
            operator_confirmed_price = (
                isinstance(_opt, Mapping)
                and _opt.get("status") == "operator_confirmed_position_price"
            )
            source_confirmed_price = (
                isinstance(_opt, Mapping) and _opt.get("status") == "source_confirmed_position_price"
            )
            attributed_position_price = operator_confirmed_price or source_confirmed_price
            # § 4: the position's money came from an answer given in the chat, so the
            # row carries the calculator's own statement of how it was applied (price,
            # unit, quantity, product, and the unit the source line itself used).
            binding["price_note"] = (
                str(_opt.get("unit_note") or "") if attributed_position_price else ""
            )
            # Directive 2.2: a position's readiness rests on four independent
            # bases; confirming a price closes only the price question. Norm
            # applicability, unit / volume correctness and the absence of
            # conflicts each require their own evidence.
            # Norm applicability is a WORK-role question: material / equipment
            # / resource / header rows have no norm to substantiate. Directive
            # 2.2 keeps their readiness independent of that check.
            role = str(binding.get("row_role") or readiness.get("row_role") or "")
            if role in {"material", "equipment", "resource", "header"} or readiness.get("header_row"):
                norm_applicability_ok = True
            else:
                norm_applicability_ok = (
                    canonicalize_norm_status(binding.get("norm_status")) != "NEEDS_RESEARCH"
                    and readiness.get("applicability_substantiated") is not False
                )
            units_ok = readiness.get("volume_verified") is not False
            # ADR-16 § 7: an amount whose only owner is the norm card is money the
            # customer has not chosen.  It stays in the document and in the
            # preliminary total; it never becomes a "confirmed" amount.
            card_priced_money = bool(pos_summary.get("card_priced_resources"))
            price_ok = bool(
                (
                    complete
                    or attributed_position_price
                    or (not pos_summary.get("completeness_reasons"))
                )
                and not (card_priced_money and not attributed_position_price)
            )
            conflicts_ok = (
                str(source_row) not in conflict_locators
                and not bool(model_row.get("confirm_ambiguous"))
                and not bool(pos_summary.get("resource_binding_conflicts"))
            )
            resource_quantities_ok = not any(
                str(reason).startswith(("quantity_missing:", "resource_amount_nonfinite:"))
                for reason in (pos_summary.get("completeness_reasons") or [])
            )
            components_calculated = "norm_components_not_calculated" not in (
                pos_summary.get("completeness_reasons") or [])
            preliminary = not (
                norm_applicability_ok and units_ok and price_ok and conflicts_ok
                and resource_quantities_ok and components_calculated
            )
            readiness["norm_applicability_ok"] = bool(norm_applicability_ok)
            readiness["units_ok"] = bool(units_ok)
            readiness["price_ok"] = bool(price_ok)
            readiness["price_from_norm_card"] = bool(card_priced_money)
            readiness["conflicts_ok"] = bool(conflicts_ok)
            readiness["operator_confirmed_price"] = bool(operator_confirmed_price)
            readiness["source_confirmed_price"] = bool(source_confirmed_price)
            readiness["prices_provided"] = (
                "не по базе"
                if card_priced_money and not attributed_position_price
                else bool(price_ok and conflicts_ok)
            )
            readiness["double_count_conflict"] = str(source_row) in conflict_locators
            # Task 2026-09-29 § 4: the two calculation questions are separate from
            # the price question and from each other.  An open reason about money
            # («price_missing:…», «card_price_without_basis:…») says the structure is
            # built and the amount is what is missing; any other open reason says the
            # structure itself is not accounted yet.  A row that arrives as zeros
            # answers "no known amount" — which is why it was never a calculated
            # position (tracker #59).
            open_reasons = [
                str(item or "") for item in (pos_summary.get("completeness_reasons") or [])
            ]
            readiness["structure_calculated"] = not [
                item
                for item in open_reasons
                if not is_price_reason(item) and not is_conflict_reason(item)
            ]
            readiness["known_amount_present"] = bool(
                amount > 0 or pos_summary.get("full_amount") is not None
            )
            readiness["position_calculated"] = bool(complete)
            readiness["open_reasons"] = list(dict.fromkeys(open_reasons))
            if complete:
                calculated_positions += 1
            # Task 2026-09-29 § 4 (tracker #54): the calculator states its resource
            # review on the position summary, and the check sheet reads it off the row.
            # Copying the facts the calculator produced (and only those) is what makes
            # the column real instead of an empty promise.
            for key in sorted(
                name
                for name in pos_summary
                if str(name).endswith("_review_status") or str(name).endswith("_review_reason")
            ):
                binding[key] = pos_summary.get(key)
            # § 4 (tracker #54): the resources the calculator actually priced travel
            # with the row, so the check sheet states them on the delivered route
            # instead of falling back to «н/п» because the input position had none.
            binding["resource_decisions"] = [
                dict(entry)
                for entry in (pos_summary.get("resource_decisions") or [])
                if isinstance(entry, Mapping)
            ]
            for key in ("resource_binding_audit", "resource_binding_conflicts", "resource_bindings", "resource_review", "separate_supply_review_audit"):
                if key in pos_summary:
                    binding[key] = pos_summary[key]
            if preliminary:
                has_preliminary_positions = True
                preliminary_amount = round(preliminary_amount + amount, 2)
            else:
                confirmed_amount = round(confirmed_amount + amount, 2)
        binding["readiness"] = readiness
        role_key = str(binding.get("row_role") or inferred_row_role(model_row))
        if role_key in kind_counts:
            kind_counts[role_key] += 1
        cipher = str(binding.get("code") or "")
        if role_key == "work" and binding.get("status") != "covered" and cipher and _is_selected_cipher(cipher):
            selected_norms += 1
            selected_ciphers.add(cipher)
    for binding in bound["row_bindings"]:
        if binding.get("status") == "covered":
            target = bound["row_bindings"][binding["coverage_target_index"]]
            # Applicability and price remain as incomplete as the billed work.
            # This is a reference to its readiness, not another calculated amount.
            binding["readiness"] = dict(target["readiness"])
            binding["position_no"] = target.get("position_no")
            binding["readiness"]["open_reasons"] = list(target["readiness"].get("open_reasons") or [])
            if _has_uncomputed_norm_components(binding.get("source_row") or {}):
                # The authored coverage link and the parent's confirmed money
                # remain intact; only this child's uncomputed request stays open.
                binding["readiness"]["structure_calculated"] = False
                binding["readiness"]["position_calculated"] = False
                binding["readiness"]["open_reasons"].append("norm_components_not_calculated")
                summary.update(result_status="priced_partial", amount_status="partial", full_amount=None)
    summary["kind_counts"] = kind_counts
    summary["selected_norms"] = selected_norms
    summary["selected_norm_ciphers"] = len(selected_ciphers)
    summary["calculated_positions"] = calculated_positions
    # Task 2026-09-29 § 4 / tracker #59: a position object is not the same fact as a
    # calculated position, so the two numbers are reported apart instead of the built
    # count being labelled "calculated".
    summary["positions_built"] = len(bound["positions"])
    summary["normative_generation_conflicts"] = sum(
        item.get("status") == "normative_generation_conflict" for item in bound["row_bindings"]
    )
    summary["normative_generation_unconfirmed_rows"] = sum(
        item.get("normative_generation_reason") == "cited_normative_generation_unconfirmed"
        for item in bound["row_bindings"]
    )
    summary["normative_source_snapshots"] = [
        dict(entry["summary"]["normative_source_snapshot"])
        for section in lsr.get("sections") or []
        for entry in section.get("positions") or []
        if (entry.get("summary") or {}).get("normative_source_snapshot")
    ]
    summary["confirmed_amount"] = confirmed_amount
    summary["preliminary_amount"] = preliminary_amount
    if has_preliminary_positions and summary.get("result_status") == "priced_final":
        summary.update(result_status="priced_partial", amount_status="partial", full_amount=None)
    if conflict_locators:
        summary["flags"] = list(summary.get("flags") or []) + [
            f"строка {locator}: двойной учёт одного предмета в ролях material и "
            "equipment — роль должна быть подтверждена явно"
            for locator in sorted(conflict_locators)
        ]
        if summary.get("result_status") == "priced_final":
            summary["result_status"] = "priced_partial"
    lsr["row_bindings"] = bound["row_bindings"]
    # Task 2026-09-29 § 4: the revision's single projection of its operations, taken
    # from the same bindings the «Проверка» sheet prints, so the readiness counts and
    # the delivered file cannot report two different states for one row.
    lsr["row_projection"] = [row_projection(item) for item in bound["row_bindings"]]
    # § 4 (tracker #54): the remarks block of the delivered file is filled from those
    # same answers instead of being left structurally empty.
    blockers, warnings = operation_open_questions(lsr["row_projection"])
    if blockers:
        lsr["blockers"] = list(lsr.get("blockers") or []) + blockers
    if warnings:
        lsr["warnings"] = list(lsr.get("warnings") or []) + warnings
    # Missing/covered/unbound main rows still own their exact authored value.
    # Do not manufacture a position just to make this unsupported field visible.
    for binding in bound["row_bindings"]:
        if binding.get("position"):
            continue
        authored = binding.get("source_row")
        if not isinstance(authored, Mapping):
            continue
        component_warnings = _norm_components_audit_warnings({
            "source_row": binding.get("row"), "op_key": operation_identity(authored),
            "norm_components": authored.get("norm_components"),
        })
        if component_warnings:
            lsr.setdefault("warnings", []).extend(component_warnings)
    return lsr
