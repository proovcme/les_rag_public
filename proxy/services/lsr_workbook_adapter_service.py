"""Thin LSR workbook adapter for decisions already made by the chat model.

The adapter performs no retrieval and never selects a norm. It binds the
model-provided norm codes to exact local cards, calculates the resulting trace,
and renders that trace to XLSX.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from proxy.services import fgis_price_service
from proxy.services.rim_lsr_trace_service import (
    build_lsr_trace_from_visible_rows,
    format_ruble_amount,
)
from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx

_QUESTION_LIKE_TITLES = {
    "собери лср",
    "составь лср",
    "сделай лср",
    "собери смету",
    "локальный сметный расчёт",
    "локальный сметный расчет",
}
_PRICE_SOURCE_LABEL = {
    "needs_kac": "КАЦ или выбранная ценовая книга",
    "needs_labor_rate": "ставка ОЗП",
    "needs_machinist_rate": "ставка ЗПМ",
    "needs_fgis_price": "цена эксплуатации машины ФГИС ЦС",
    "card_price_without_basis": "выбранная ценовая книга, КАЦ или подтверждённая цена",
    # ADR-16 § 7 applied to accruals: a percentage printed in the norm card is
    # not a basis, and § 11 №6 lists НР and СП among what a known price may not
    # mask.  Both cases ask the operator instead of answering for them.
    "nr_sp_without_basis": "нормативное основание (812/пр, 774/пр) или явный выбор ставки",
    "nr_sp_unresolved": "нормативное основание (812/пр, 774/пр) или явный выбор ставки",
}
_QUARTER_RE = re.compile(
    r"(?i)(?P<num>[1-4]|III|II|IV|I)\s*(?:квартал\w*|кв\.?)\s*(?P<year>20\d{2})"
)
# A book file name carries the period too: "sankt-peterburg_2kv2026".
_FILE_QUARTER_RE = re.compile(r"(?i)(?P<num>[1-4])\s*kv\.?\s*(?P<year>20\d{2})")
_QUARTER_ROMAN_TO_DIGIT = {"I": "1", "II": "2", "III": "3", "IV": "4"}
_LABEL_RES = (
    ("customer", re.compile(r"(?im)^\s*заказчик\s*[:\-–]\s*(.+?)\s*$")),
    ("object", re.compile(
        r"(?im)^\s*объект(?:\s+капитального\s+строительства)?\s*[:\-–]\s*(.+?)\s*$"
    )),
    ("stroika", re.compile(
        r"(?im)^\s*(?:стройка|наименование\s+стройки)\s*[:\-–]\s*(.+?)\s*$"
    )),
    ("basis", re.compile(r"(?im)^\s*основание\s*[:\-–]\s*(.+?)\s*$")),
    ("title", re.compile(
        r"(?im)^\s*(ведомость\s+объ[её]м(?:а|ов)\s+работ[^\n]*)\s*$"
    )),
)


def _clean_identity_value(value: str) -> str:
    text = " ".join(str(value or "").replace("\u00a0", " ").split())
    return text.strip(" .;:-")


def is_question_like_title(value: str) -> bool:
    cleaned = _clean_identity_value(value).casefold()
    if cleaned in _QUESTION_LIKE_TITLES:
        return True
    sanitized = re.sub(r"[^\w\-]+", "_", cleaned, flags=re.UNICODE).strip("._").casefold()
    return sanitized in {
        re.sub(r"[^\w\-]+", "_", item, flags=re.UNICODE).strip("._")
        for item in _QUESTION_LIKE_TITLES
    }


def extract_lsr_source_identity(
    *,
    source_text: str = "",
    source_name: str = "",
) -> dict[str, str]:
    """Labeled VOR identity only. Never uses the chat question as a title."""

    filename = Path(str(source_name or "").strip()).name
    stem = Path(filename).stem if filename else ""
    fields: dict[str, str] = {}
    for key, pattern in _LABEL_RES:
        match = pattern.search(str(source_text or ""))
        if match:
            cleaned = _clean_identity_value(match.group(1))
            if cleaned:
                fields[key] = cleaned
    title = fields.get("title") or stem
    if is_question_like_title(title):
        title = stem
    if is_question_like_title(title):
        title = ""
    title = title or "Локальный сметный расчёт"
    quarter = _QUARTER_RE.search(str(source_text or ""))
    price_level = (
        f"{quarter.group('num')} квартал {quarter.group('year')}"
        if quarter
        else "—"
    )
    stroika = fields.get("stroika") or ""
    customer = fields.get("customer") or ""
    if not stroika and customer:
        stroika = customer
    return {
        "title": title,
        "object": fields.get("object") or "",
        "stroika": stroika,
        "customer": customer,
        "osnovanie": fields.get("basis") or filename or "—",
        "price_level": price_level,
    }


def _read_source_preview_text(path: Path) -> str:
    if path.suffix.lower() != ".pdf" or not path.exists():
        return ""
    try:
        import pymupdf as fitz
    except Exception:
        try:
            import fitz
        except Exception:
            return ""
    try:
        with fitz.open(str(path)) as document:
            pages: list[str] = []
            for index, page in enumerate(document):
                if index >= 2:
                    break
                pages.append(page.get_text() or "")
            return "\n".join(pages)
    except Exception:
        return ""


def _quarter_token(value: object) -> str:
    text = str(value or "")
    match = _QUARTER_RE.search(text) or _FILE_QUARTER_RE.search(text)
    if not match:
        return ""
    raw = match.group("num")
    num = _QUARTER_ROMAN_TO_DIGIT.get(raw.upper(), raw)
    return f"{num}:{match.group('year')}"


def _quarter_phrase(value: object) -> str:
    match = _QUARTER_RE.search(str(value or ""))
    return " ".join(match.group(0).split()) if match else ""


_REGION_PATTERNS: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    # (any-of tokens, none-of tokens, canonical subject). Order is
    # significant: an oblast is checked before its capital, because a capital
    # and a price zone of the same name are not the same basis (ADR-16 § 7).
    (
        ("ленинградск", "ленінградск", "leningradsk", "ленинградская"),
        (),
        "Ленинградская область",
    ),
    (
        ("московск",),
        ("город", "москва"),
        "Московская область",
    ),
    (
        ("санкт-петербург", "санкт петербург", "петербург", "спб", "ленинград",
         "sankt", "peterburg", "spb", "leningrad"),
        (),
        "Санкт-Петербург",
    ),
    (
        ("москв", "moskva", "moscow"),
        (),
        "Москва",
    ),
)
# An oblast is its own price zone; naming it must not be read as naming its
# capital, and the reverse never happens (the capital token is not a substring
# of the oblast name).
_REGION_SUPERSESSIONS = {
    "Ленинградская область": "Санкт-Петербург",
    "Московская область": "Москва",
}


def _region_in_text(value: object) -> str:
    text = str(value or "").casefold().replace("ё", "е")
    if not text.strip():
        return ""
    for patterns, excludes, canonical in _REGION_PATTERNS:
        if any(token in text for token in patterns) and not any(
            token in text for token in excludes
        ):
            return canonical
    return ""


def _region_candidates(value: object) -> set[str]:
    """Every distinct subject named in one text.

    City and price zone are never identified with each other here: a text that
    names both produces two candidates, and the caller must not resolve that
    conflict by picking one. An oblast names its capital too, so the oblast is
    kept and the capital dropped instead of reporting a false conflict.
    """

    text = str(value or "").casefold().replace("ё", "е")
    found: set[str] = set()
    for patterns, excludes, canonical in _REGION_PATTERNS:
        if not any(token in text for token in patterns):
            continue
        if any(token in text for token in excludes):
            continue
        found.add(canonical)
    for oblast, capital in _REGION_SUPERSESSIONS.items():
        if oblast in found:
            found.discard(capital)
    return found


def visible_pricebook_stems() -> list[str]:
    """Identifiers of the installed, operator-selectable price books."""

    try:
        return sorted(
            Path(path).stem for path in fgis_price_service.available_pricebooks()
        )
    except Exception:  # noqa: BLE001 - a missing catalog is reported, not guessed
        return []


def explicit_estimate_pricebook(
    *,
    requested_book: str = "",
    operator_book: str = "",
    region_text: str = "",
    question_text: str = "",
    source_text: str = "",
    source_name: str = "",
    pricebooks: Sequence[object] | None = None,
) -> dict[str, Any]:
    """Bind a price book only when the basis is explicit (ADR-16 § 7).

    Three origins are accepted, in this order and never mixed silently: the
    calculation parameter, the operator's confirmation stored on the active
    revision, and a unique derived match of an explicitly named subject plus an
    explicitly written quarter against the installed catalog. Anything else
    returns an empty book with the visible list of what is installed, so the
    estimate stays a draft and the operator is asked — the configured default is
    not allowed to price an estimate nobody chose.
    """

    stems = [
        str(stem).strip()
        for stem in (
            visible_pricebook_stems() if pricebooks is None else list(pricebooks)
        )
        if str(stem or "").strip()
    ]
    result: dict[str, Any] = {
        "pricebook": "",
        "origin": "",
        "reason": "",
        "requested_region": "",
        "requested_quarter": "",
        "basis_binding": "",
        "available_books": stems,
    }
    if requested_book.strip():
        result["origin"] = "параметр расчёта"
        result["reason"] = "книга задана явно в параметре расчёта"
        result["pricebook"] = requested_book.strip()
        result["basis_binding"] = requested_book.strip()
        return result
    if operator_book.strip():
        result["origin"] = "подтверждение оператора"
        result["reason"] = "базу выбрал пользователь и подтвердил в текущей ревизии"
        result["pricebook"] = operator_book.strip()
        result["basis_binding"] = operator_book.strip()
        return result
    if not stems:
        result["reason"] = "локально нет ни одной доступной ценовой книги"
        return result

    named: list[tuple[str, str]] = []
    if region_text.strip():
        named.append(("параметр расчёта", region_text))
    if question_text.strip():
        named.append(("задача", question_text))
    if source_text.strip():
        named.append(("исходник", source_text))
    if source_name.strip():
        named.append(("имя исходника", source_name))
    regions: set[str] = set()
    region_origin = ""
    for origin, text in named:
        found = _region_candidates(text)
        if found and not regions:
            region_origin = origin
        regions |= found
    quarters: set[str] = set()
    quarter_origin = ""
    for origin, text in named:
        token = _quarter_token(text)
        if token and token not in quarters:
            if not quarters:
                quarter_origin = origin
            quarters.add(token)
    if len(regions) > 1:
        result["reason"] = "регион назван по-разному в задаче, исходнике или параметре"
        return result
    if len(quarters) > 1:
        result["reason"] = "период цен назван по-разному в задаче, исходнике или параметре"
        return result
    result["requested_region"] = next(iter(regions)) if regions else ""
    result["requested_quarter"] = next(iter(quarters)) if quarters else ""
    result["basis_binding"] = " ".join(
        part
        for part in (
            result["requested_region"],
            _quarter_phrase(" ".join(text for _, text in named)),
        )
        if part
    ).strip()
    if not regions and not quarters:
        result["reason"] = (
            "в задаче и исходнике явно не названы ни субъект, ни период — "
            "книга по умолчанию не подставляется"
        )
        return result
    if not regions:
        result["reason"] = (
            "в явном тексте назван период, но не назван (или не распознан) "
            "субъект — книгу не подставляют молча"
        )
        return result
    if not quarters:
        result["reason"] = (
            "в явном тексте назван субъект, но не назван квартал и год — "
            "книгу не подставляют молча"
        )
        return result

    requested_quarter = result["requested_quarter"]
    matches = [
        stem
        for stem in stems
        if _region_in_text(stem) == result["requested_region"]
        and _quarter_token(stem) == requested_quarter
    ]
    if len(matches) == 1:
        result["pricebook"] = matches[0]
        result["origin"] = (
            f"выведено из: {region_origin} + {quarter_origin} "
            "(единственная подходящая книга)"
        )
        result["reason"] = "субъект и период названы явно и совпали ровно с одной книгой"
        return result
    if not matches:
        result["reason"] = (
            "среди доступных книг нет книги для названных субъекта и периода; "
            "запрошенную базу не подменяют другой книгой"
        )
        return result
    result["reason"] = "для названных субъекта и периода подходит несколько книг"
    return result


def summarize_lsr_price_basis(
    *,
    requested_book: str = "",
    source_price_level: str = "",
    question_text: str = "",
    pricebook=None,
    pricebook_name: str = "",
    requested_region: str = "",
    requested_region_origin: str = "",
    operator_confirmation: Mapping[str, Any] | None = None,
    pricebook_origin: str = "",
    available_books: Sequence[object] = (),
    basis_binding: str = "",
) -> dict[str, Any]:
    """Bind the requested and the actually applied price basis; mismatches stay visible.

    Region, year, quarter and the book identity are checked together. Contradictions
    between explicit parameters are never resolved by hidden priority: they are
    reported, and only an operator confirmation can accept an alternative basis.

    ``pricebook_origin`` states which explicit source the applied book came from
    (parameter, operator confirmation, or a unique derived match), so the chosen
    basis is visible instead of implied; ``available_books`` lists the installed
    identifiers whenever no book could be bound (ADR-16 § 7).
    """

    requested_parts: list[str] = []
    book_request = str(requested_book or "").strip()
    if book_request:
        requested_parts.append(book_request)
    source_level = str(source_price_level or "").strip()
    if source_level and source_level != "—":
        requested_parts.append(source_level)
    question_level = _quarter_phrase(question_text)
    if question_level and question_level not in requested_parts:
        requested_parts.append(question_level)
    # A subject and period written in the task or the file are a requested
    # basis even when no book could be bound to them (ADR-16 § 7).
    binding = str(basis_binding or "").strip()
    if binding and binding not in requested_parts:
        requested_parts.append(binding)
    requested_label = "; ".join(requested_parts)

    region_text = str(requested_region or "").strip()
    if region_text:
        region_text = _region_in_text(region_text) or region_text
        region_origin = str(requested_region_origin or "").strip() or "параметр расчёта"
    else:
        region_origin = ""
        for candidate, origin in (
            (book_request, "запрошенная книга"),
            (question_text, "вопрос"),
            (source_level, "исходник"),
        ):
            found = _region_in_text(candidate)
            if found:
                region_text = found
                region_origin = f"выведено из: {origin}"
                break
    if not region_text:
        region_origin = "не указан"

    # A contradiction between explicit parameters must never be resolved by a
    # hidden priority: collect every distinct token instead.
    requested_regions = {
        found
        for found in (
            _region_in_text(book_request),
            _region_in_text(question_text),
            _region_in_text(source_level),
        )
        if found
    }
    quarter_tokens = {
        token
        for token in (
            _quarter_token(book_request),
            _quarter_token(source_level),
            _quarter_token(question_level),
        )
        if token
    }
    contradictions: list[str] = []
    if len(requested_regions) > 1:
        contradictions.append("регион: " + ", ".join(sorted(requested_regions)))
    if len(quarter_tokens) > 1:
        contradictions.append("период цен: " + ", ".join(sorted(quarter_tokens)))
    requested_quarter = next(iter(quarter_tokens)) if len(quarter_tokens) == 1 else ""

    confirmation = (
        operator_confirmation if isinstance(operator_confirmation, Mapping) else None
    )
    confirmed_book = str((confirmation or {}).get("pricebook") or "").strip()
    # The operator has to be able to choose from what actually exists, so the
    # installed identifiers travel with the "no book applied" state (§ 7).
    visible_books = [
        str(stem).strip()
        for stem in (available_books or ())
        if str(stem or "").strip()
    ]
    available_hint = (
        " Доступные книги: " + ", ".join(visible_books[:20])
        + ("" if len(visible_books) <= 20 else f" … (всего {len(visible_books)})")
        if visible_books
        else " Локально нет ни одной доступной ценовой книги."
    )

    if pricebook is None:
        return {
            "requested": requested_label,
            "requested_region": region_text,
            "requested_region_origin": region_origin,
            "contradictions": contradictions,
            "actual_book": "",
            "actual_region": "",
            "actual_quarter": "",
            "origin": "",
            "available_books": visible_books,
            "requested_book": book_request,
            "requested_basis_present": bool(requested_label),
            "match": "no_book",
            "note": (
                (
                    f"Запрошенная ценовая база «{requested_label}» локально не найдена "
                    f"и не подменена другой книгой.{available_hint}"
                    if requested_label
                    else
                    f"Ценовая база не задана явно, поэтому книга не выбрана и цены "
                    f"не подставлены молча.{available_hint}"
                )
                + " Расчёт без книги остаётся черновиком: считаются подтверждённые"
                " оператором цены, цены КАЦ и помеченные цены из карточек нормы."
                " Выберите книгу из списка выше или внесите цены через подтверждённые данные."
            ),
        }
    actual_region = str(getattr(pricebook, "region", "") or "")
    actual_quarter = str(getattr(pricebook, "quarter", "") or "")
    actual_label = actual_quarter or str(pricebook_name or "")
    subject_label = actual_region or "субъект не указан"
    actual_region_token = _region_in_text(actual_region) or _region_in_text(pricebook_name)
    checks: list[bool] = []
    if book_request:
        checks.append(book_request.casefold() in str(pricebook_name or "").casefold())
    actual_quarter_token = _quarter_token(actual_quarter) or _quarter_token(pricebook_name)
    if requested_quarter:
        checks.append(bool(actual_quarter_token) and requested_quarter == actual_quarter_token)
    if region_text and actual_region_token:
        checks.append(region_text == actual_region_token)
    if contradictions:
        checks.append(False)
    if checks and all(checks):
        match = "exact"
        note = f"Ценовая база совпадает с запросом: {actual_label} ({subject_label})."
        origin_label = str(pricebook_origin or "").strip()
        if origin_label:
            note += f" Источник выбора базы: {origin_label}."
    elif checks:
        match = "mismatch"
        note = (
            f"Запрошена ценовая база «{requested_label}"
            + (f" (регион: {region_text})" if region_text else "")
            + f"», фактически применена «{actual_label}» ({subject_label}). "
            "Расчёт по фактической базе не считается расчётом по запросу: "
            "подтвердите альтернативу явно — пересоберите с книгой запрошенной базы "
            "(явный аргумент pricebook) или внесите подтверждённые цены через "
            "«Внести подтверждённые данные»."
        )
        if contradictions:
            note = (
                "Явные параметры противоречат друг другу ("
                + "; ".join(contradictions)
                + "). "
                + note
            )
        if confirmed_book and (
            confirmed_book.casefold() in str(pricebook_name or "").casefold()
            or str(pricebook_name or "").casefold() in confirmed_book.casefold()
        ):
            match = "confirmed_alternative"
            note = (
                f"Альтернативная ценовая база «{actual_label}» ({subject_label}) "
                "подтверждена оператором как согласованное отклонение; расчёт по "
                "запрошенной базе не подменён."
            )
    else:
        match = "unspecified"
        note = (
            f"Ценовая база в запросе и исходнике не указана; применено «{actual_label}» "
            f"({subject_label}). Подтвердите, что эта база соответствует требуемому периоду."
        )
    return {
        "requested": requested_label,
        "requested_book": book_request,
        "requested_region": region_text,
        "requested_region_origin": region_origin,
        "contradictions": contradictions,
        "actual_book": str(pricebook_name or ""),
        "actual_region": actual_region,
        "actual_quarter": actual_quarter,
        "origin": str(pricebook_origin or ""),
        "available_books": visible_books,
        "match": match,
        "note": note,
    }


def collect_lsr_workbook_gaps(trace: Mapping[str, Any]) -> list[str]:
    """Operator-visible bind/price gaps. Code does not choose replacement norms."""

    gaps: list[str] = []
    for binding in trace.get("row_bindings") or []:
        if not isinstance(binding, Mapping):
            continue
        if str(binding.get("status") or "") in {
            "bound",
            "resource_linked",
            "structure_accounted",
        }:
            continue
        gaps.append(
            f"row:{binding.get('row')}:{binding.get('status') or 'unresolved'}"
        )
    for section in trace.get("sections") or []:
        if not isinstance(section, Mapping):
            continue
        for position in section.get("positions") or []:
            if not isinstance(position, Mapping):
                continue
            reasons = (position.get("summary") or {}).get("completeness_reasons") or []
            for reason in reasons:
                text = str(reason)
                if text.startswith("price_missing:"):
                    gaps.append(text)
    return gaps


def collect_lsr_card_prices(trace: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Resources whose money came out of the norm card instead of a basis.

    The number is not deleted from the document — it is named, so the operator
    can replace it with a book price, a КАЦ price or their own confirmation
    (ADR-16 § 7).
    """

    found: list[dict[str, Any]] = []
    for section in trace.get("sections") or []:
        if not isinstance(section, Mapping):
            continue
        for position in section.get("positions") or []:
            if not isinstance(position, Mapping):
                continue
            summary = (
                position.get("summary")
                if isinstance(position.get("summary"), Mapping)
                else {}
            )
            for item in summary.get("card_priced_resources") or []:
                if not isinstance(item, Mapping):
                    continue
                found.append(
                    {
                        **dict(item),
                        "position_code": str(position.get("code") or ""),
                        "position_name": str(position.get("name") or ""),
                        "locator": position.get("source_row"),
                    }
                )
    return found


def collect_lsr_action_conflicts(trace: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Rows whose own words name the opposite operation from the chosen norm.

    The cipher the model selected is never rewritten here; the list exists so
    the readiness channels ask one concrete question about it (task § 11 №8).
    """

    found: list[dict[str, Any]] = []
    for binding in trace.get("row_bindings") or []:
        if not isinstance(binding, Mapping):
            continue
        conflict = binding.get("action_conflict")
        if not (isinstance(conflict, Mapping) and conflict):
            continue
        found.append(
            {
                **dict(conflict),
                "locator": str(binding.get("row") or ""),
                "code": str(binding.get("code") or ""),
            }
        )
    return found


def describe_lsr_card_prices(
    card_priced: Sequence[Mapping[str, Any]], *, limit: int = 6
) -> str:
    """The header sentence naming money that came out of the norm cards.

    The same rate normally repeats across several ВОР rows, so resources are
    grouped by what the operator actually recognises (name, code, unit, rate)
    and each group names the rows it was applied to.  Nothing is dropped and
    nothing is presented as a distinct amount twice (ADR-16 § 7).
    """

    grouped: dict[tuple[str, str, str], list[str]] = {}
    for item in card_priced:
        name = str(item.get("name") or item.get("code") or "ресурс")
        code = str(item.get("code") or "")
        price = item.get("price")
        unit = str(item.get("unit") or "")
        rate = (
            f"{format_ruble_amount(price, exact=True)} руб."
            if isinstance(price, (int, float)) and not isinstance(price, bool)
            else ""
        )
        locator = str(item.get("locator") or item.get("position_code") or "")
        grouped.setdefault((name, code, rate + "|" + unit), []).append(locator)
    labels: list[str] = []
    for (name, code, rate_unit), locators in list(grouped.items())[:limit]:
        label = name + (f" ({code})" if code and code != name else "")
        rate, _, unit = rate_unit.partition("|")
        if rate:
            label += f" — {rate}" + (f"/{unit}" if unit else "")
        rows = [locator for locator in dict.fromkeys(locators) if locator]
        if rows:
            label += ", строки " + ", ".join(rows[:4]) + (
                f" … (ещё {len(rows) - 4})" if len(rows) > 4 else ""
            )
        labels.append(label)
    total_rows = len(
        {
            locator
            for locators in grouped.values()
            for locator in locators
            if locator
        }
    ) or len(card_priced)
    tail = (
        f" … (показаны {limit} из {len(grouped)} ресурсов, "
        f"строк с ценой из карточки нормы всего: {total_rows})"
        if len(grouped) > limit
        else ""
    )
    return (
        " Часть посчитанных ресурсов взята не из ценовой базы, а из карточки нормы: "
        + "; ".join(labels)
        + tail
        + ". Такие позиции остаются черновиком: подтвердите книгу, КАЦ или свою цену."
    )


def _nr_sp_gap(
    position: Mapping[str, Any],
    *,
    position_label: str,
    checked_basis: str,
) -> dict[str, Any] | None:
    """One operator question per position whose НР/СП rate has no owner.

    Two cases reach the customer's document: the rate was printed in the norm
    card (ADR-16 § 7: not a basis, so the amount is known but the position stays
    a draft), and the rate is simply absent (№ 11's «известная цена не маскирует
    отсутствие НР/СП»).  Neither is answered here — the entry names what was
    used and who may confirm it.
    """

    summary = (
        position.get("summary") if isinstance(position.get("summary"), Mapping) else {}
    )
    ownership = (
        summary.get("nr_sp_ownership")
        if isinstance(summary.get("nr_sp_ownership"), Mapping)
        else {}
    )
    label = str(ownership.get("label") or "")
    if label not in _PRICE_SOURCE_LABEL:
        return None
    code = str(position.get("code") or "")

    def rate(key: str) -> str:
        value = ownership.get(key)
        return (
            f"{value:g} %"
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else "нет"
        )

    if label == "nr_sp_without_basis":
        action_text = (
            f"НР ({rate('nr_pct')}) и СП ({rate('sp_pct')}) по позиции "
            f"{position_label or 'без шифра'} взяты из карточки нормы, а не из"
            " нормативного основания или вашего явного выбора. Подтвердите"
            " правило начисления или задайте ставки сами — без этого позиция"
            " остаётся черновиком."
        )
    else:
        candidates = summary.get("nr_sp_trace", {}).get("candidates") if isinstance(
            summary.get("nr_sp_trace"), Mapping
        ) else None
        listing = (
            f" Подходящих правил в каталоге: {len(candidates)} — нужно одно."
            if isinstance(candidates, (list, tuple)) and candidates
            else ""
        )
        action_text = (
            f"Для позиции {position_label or 'без шифра'} начисления НР"
            f" ({rate('nr_pct')}) и СП ({rate('sp_pct')}) не определены:"
            " нормативное основание не выбрано, в карточке нормы ставки нет."
            + listing
            + " Расчёт без НР и СП не становится полной сметой."
        )
    # the readiness projection keeps one entry per distinct resource name, so a
    # 300-position document would otherwise report a single НР/СП question
    resource = f"НР и СП ({position_label})" if position_label else "НР и СП"
    return {
        "resource": resource,
        "code": code,
        "quantity": None,
        "unit": "% от ФОТ",
        "price_action": label,
        "required_source": _PRICE_SOURCE_LABEL[label],
        "position_code": code,
        "position_name": str(position.get("name") or ""),
        "dependent_calculations": [
            f"итог позиции {position_label or 'без шифра'}",
            "ФОТ, НР и СП этой позиции",
        ],
        "checked_basis": checked_basis,
        "action": action_text,
    }


def collect_lsr_price_gaps(
    trace: Mapping[str, Any],
    *,
    pricebook=None,
    pricebook_name: str = "",
) -> list[dict[str, Any]]:
    """Price holes per position: resource, quantity+unit, basis checked. Not zeros."""

    basis_region = (
        str(getattr(pricebook, "region", "") or "") if pricebook is not None else ""
    )
    basis_quarter = (
        str(getattr(pricebook, "quarter", "") or "") if pricebook is not None else ""
    )
    checked_basis = "; ".join(
        part
        for part in (basis_quarter or str(pricebook_name or ""), basis_region)
        if part
    )
    gaps: list[dict[str, Any]] = []
    for section in trace.get("sections") or []:
        if not isinstance(section, Mapping):
            continue
        for position in section.get("positions") or []:
            if not isinstance(position, Mapping):
                continue
            position_code = str(position.get("code") or "")
            position_name = str(position.get("name") or "")
            position_label = position_code or position_name
            for row in position.get("rows") or []:
                if not isinstance(row, Mapping):
                    continue
                meta = row.get("meta") if isinstance(row.get("meta"), Mapping) else {}
                action = str(meta.get("price_action") or "").strip()
                if not action:
                    continue
                columns = row.get("columns") if isinstance(row.get("columns"), Mapping) else {}
                code = str(columns.get(2, columns.get("2")) or "")
                name = str(row.get("name") or columns.get(3, columns.get("3")) or code or "ресурс")
                quantity = columns.get(7, columns.get("7"))
                unit = str(columns.get(4, columns.get("4")) or "")
                required = _PRICE_SOURCE_LABEL.get(action, "подтверждённая цена")
                card_amount = columns.get(10, columns.get("10"))
                identity = name if name != code else (code or name)
                named = (
                    f"Для {name}"
                    if action == "card_price_without_basis"
                    else f"Задайте цену для {name}"
                ) + (f" ({code})" if code and code != name else "") + (
                    f" в позиции {position_label}" if position_label else ""
                )
                if action == "card_price_without_basis":
                    # Money exists but nobody owns the number: the question names
                    # the rate actually applied and asks for its owner (ADR-16 § 7).
                    rate_text = (
                        f" ({format_ruble_amount(card_amount, exact=True)} руб."
                        + (f"/{unit}" if unit else "")
                        + ")"
                        if isinstance(card_amount, (int, float))
                        and not isinstance(card_amount, bool)
                        else ""
                    )
                    action_text = (
                        named
                        + f" посчитано по цене из карточки нормы{rate_text}, а не по"
                        + " выбранной ценовой базе, КАЦ или подтверждённой цене."
                        + " Подтвердите книгу, КАЦ или свою цену — без этого позиция"
                        " остаётся черновиком."
                    )
                else:
                    action_text = (
                        named
                        + (f", количество {quantity}" if quantity not in (None, "") else "")
                        + (f" {unit}" if unit else "")
                        + f". Источник: {required}."
                        + (
                            f" Проверенная ценовая база: {checked_basis}."
                            if checked_basis
                            else ""
                        )
                        + " Отсутствие цены не отменяет норму."
                    )
                gaps.append(
                    {
                        "resource": identity,
                        "code": code,
                        "quantity": quantity,
                        "unit": unit,
                        "price_action": action,
                        "required_source": required,
                        "position_code": position_code,
                        "position_name": position_name,
                        "dependent_calculations": [
                            f"итог позиции {position_label or 'без шифра'}",
                            "прямые затраты, НР и СП этой позиции",
                        ],
                        "checked_basis": checked_basis,
                        "action": action_text,
                    }
                )
            accrual_gap = _nr_sp_gap(
                position,
                position_label=position_label,
                checked_basis=checked_basis,
            )
            if accrual_gap is not None:
                gaps.append(accrual_gap)
    return gaps


def _attach_catalog_facts(
    decisions: list[dict[str, Any]], attachment_id: str
) -> None:
    """Stamp raw source cells/numbers so the calculator can reject silent changes.

    Source data is kept separately from the authored row; nothing is rewritten.
    A missing attachment or catalog keeps the legacy calculation path.
    """

    if not attachment_id or not decisions:
        return
    try:
        from proxy.services.attachment_source_catalog_service import (
            load_catalog_from_attachment_id,
            quantity_candidates,
        )

        catalog = load_catalog_from_attachment_id(attachment_id)
    except Exception:  # noqa: BLE001 - catalog absence cannot break a rebuild
        catalog = None
    if catalog is None:
        return
    for item in decisions:
        try:
            cat_row = catalog.lookup(item.get("source_row"))
        except Exception:  # noqa: BLE001
            continue
        if cat_row is None:
            continue
        item["_catalog_source_values"] = [str(value) for value in cat_row.values]
        item["_catalog_source_numbers"] = [
            float(value) for value in quantity_candidates(cat_row)
        ]
        item["_catalog_source_quantity_known"] = bool(
            getattr(cat_row, "quantity_column_known", False)
        )


async def build_lsr_workbook_from_decisions(
    _source_path: Path,
    args: Mapping[str, Any],
    output_path: Path,
    progress: Callable[[str, int, int | None], None],
) -> Mapping[str, Any]:
    """Calculate and render the model's explicit LSR row decisions."""
    decisions = [dict(item) for item in (args.get("decisions") or [])]
    _attach_catalog_facts(decisions, str(args.get("attachment_id") or "").strip())
    requested_pricebook = str(
        args.get("pricebook") or args.get("pricebook_id") or ""
    ).strip()
    source_name = str(args.get("_source_name") or _source_path.name or "")
    source_text = str(args.get("_source_text") or "") or _read_source_preview_text(
        Path(_source_path)
    )
    overlays = (
        args.get("confirmed_data")
        if isinstance(args.get("confirmed_data"), Mapping)
        else None
    )
    basis_confirmation = None
    if (
        isinstance(overlays, Mapping)
        and isinstance(overlays.get("_price_basis"), Mapping)
    ):
        basis_confirmation = dict(overlays["_price_basis"])
        basis_confirmation.setdefault("confirmed_by", "operator")
    operator_book = str((basis_confirmation or {}).get("pricebook") or "").strip()
    requested_region = str(
        args.get("region") or args.get("price_region") or ""
    ).strip()
    # ADR-16 § 7: only an explicit basis may bind a book. The configured default
    # is not allowed to price an estimate whose region and period nobody chose.
    basis_choice = explicit_estimate_pricebook(
        requested_book=requested_pricebook,
        operator_book=operator_book,
        region_text=requested_region,
        question_text=str(args.get("question") or ""),
        source_text=source_text,
        source_name=source_name,
    )
    pricebook_path = fgis_price_service.resolve_pricebook_path(
        basis_choice["pricebook"] or None, explicit_only=True
    )
    pricebook = (
        fgis_price_service.get_pricebook(pricebook_path)
        if pricebook_path
        else None
    )
    pricebook_name = Path(pricebook_path).stem if pricebook_path else ""
    identity = extract_lsr_source_identity(
        source_text=source_text,
        source_name=source_name,
    )
    price_basis = summarize_lsr_price_basis(
        requested_book=requested_pricebook or operator_book,
        source_price_level=identity["price_level"],
        question_text=str(args.get("question") or ""),
        pricebook=pricebook,
        pricebook_name=pricebook_name,
        requested_region=requested_region,
        requested_region_origin=(
            "параметр расчёта"
            if requested_region
            else ""
        ),
        operator_confirmation=basis_confirmation,
        pricebook_origin=str(basis_choice["origin"] or ""),
        available_books=basis_choice["available_books"],
        basis_binding=str(basis_choice["basis_binding"] or ""),
    )
    progress("model_decisions", 0, len(decisions))
    overlays = args.get("confirmed_data") if isinstance(args.get("confirmed_data"), Mapping) else None
    trace = await asyncio.to_thread(
        build_lsr_trace_from_visible_rows,
        decisions,
        pricebook=pricebook,
        name=identity["title"],
        confirmed_data=overlays,
    )
    source_label = "" if is_question_like_title(Path(source_name).stem) else source_name
    card_priced = collect_lsr_card_prices(trace)
    if card_priced:
        # ADR-16 § 7: the header may not claim that nothing was priced while the
        # norm cards themselves supplied numbers.  Those amounts stay visible and
        # are named as not belonging to the chosen basis.
        card_note = describe_lsr_card_prices(card_priced)
        price_basis = {
            **price_basis,
            "card_priced_resources": card_priced,
            "card_priced_note": card_note.strip(),
            "note": str(price_basis.get("note") or "") + card_note,
        }
    render_meta = {
        "source": source_label,
        "pricebook": pricebook_name,
        "osnovanie": identity["osnovanie"],
        "price_level": identity["price_level"],
    }
    if pricebook_name:
        # The header states the level actually applied, never a default implied
        # by an absent source period.
        render_meta["price_level"] = (
            price_basis["actual_quarter"]
            if str(price_basis.get("actual_quarter") or "").strip()
            else pricebook_name
        )
    if identity["object"]:
        render_meta["object"] = identity["object"]
    if identity["stroika"]:
        render_meta["stroika"] = identity["stroika"]
    if pricebook is not None:
        render_meta["subject"] = str(getattr(pricebook, "region", "") or "Не указан")
    render_meta["price_basis_note"] = price_basis["note"]
    render_meta["price_basis_match"] = price_basis["match"]
    await asyncio.to_thread(
        render_lsr_xlsx,
        trace,
        output_path,
        title=identity["title"],
        meta=render_meta,
    )
    progress("model_decisions", len(decisions), len(decisions))

    missing = collect_lsr_workbook_gaps(trace)
    return {
        "file_path": output_path,
        "source_rows": len(decisions),
        "pricebook": pricebook_name,
        "pricing_status": str((trace.get("summary") or {}).get("result_status") or ""),
        "norms_status": str((trace.get("summary") or {}).get("norms_status") or ""),
        # which explicit source bound the book, and why nothing was bound
        "price_basis_choice": basis_choice,
        "missing": missing,
        "price_gaps": collect_lsr_price_gaps(
            trace,
            pricebook=pricebook,
            pricebook_name=pricebook_name,
        ),
        "price_basis": price_basis,
        # rows whose own wording names the opposite operation from the chosen
        # norm: a question for the operator, never a silent re-selection
        "norm_conflicts": collect_lsr_action_conflicts(trace),
        # stage V operator counts: calculated positions and the confirmed /
        # preliminary split of the known amount (code arithmetic, no statuses raised)
        "calculated_positions": int(
            (trace.get("summary") or {}).get("calculated_positions") or 0
        ),
        "confirmed_amount": float(
            (trace.get("summary") or {}).get("confirmed_amount") or 0.0
        ),
        "preliminary_amount": float(
            (trace.get("summary") or {}).get("preliminary_amount") or 0.0
        ),
        # A zero-priced result is still a useful audit workbook. Unresolved
        # rows and their reasons remain in ``missing`` and the rendered trace.
        "blockers": [],
    }
