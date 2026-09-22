"""Thin LSR workbook adapter for decisions already made by the chat model.

The adapter performs no retrieval and never selects a norm. It binds the
model-provided norm codes to exact local cards, calculates the resulting trace,
and renders that trace to XLSX.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from proxy.services import fgis_price_service
from proxy.services.rim_lsr_trace_service import build_lsr_trace_from_visible_rows
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
}
_QUARTER_RE = re.compile(
    r"(?i)(?P<num>[1-4]|III|II|IV|I)\s*(?:квартал\w*|кв\.?)\s*(?P<year>20\d{2})"
)
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
    match = _QUARTER_RE.search(str(value or ""))
    if not match:
        return ""
    raw = match.group("num")
    num = _QUARTER_ROMAN_TO_DIGIT.get(raw.upper(), raw)
    return f"{num}:{match.group('year')}"


def _quarter_phrase(value: object) -> str:
    match = _QUARTER_RE.search(str(value or ""))
    return " ".join(match.group(0).split()) if match else ""


def summarize_lsr_price_basis(
    *,
    requested_book: str = "",
    source_price_level: str = "",
    question_text: str = "",
    pricebook=None,
    pricebook_name: str = "",
) -> dict[str, Any]:
    """Bind the requested and the actually applied price basis; mismatches stay visible."""

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
    requested_label = "; ".join(requested_parts)
    if pricebook is None:
        return {
            "requested": requested_label,
            "actual_book": "",
            "actual_region": "",
            "actual_quarter": "",
            "match": "no_book",
            "note": (
                (
                    f"Запрошенная ценовая база «{requested_label}» локально не найдена. "
                    if requested_label
                    else ""
                )
                + "Ценовая книга не применена: расчёт идёт только по подтверждённым ценам и КАЦ. "
                "Укажите доступную книгу или внесите цены через подтверждённые данные."
            ),
        }
    actual_region = str(getattr(pricebook, "region", "") or "")
    actual_quarter = str(getattr(pricebook, "quarter", "") or "")
    actual_label = actual_quarter or str(pricebook_name or "")
    subject_label = actual_region or "субъект не указан"
    checks: list[bool] = []
    if book_request:
        checks.append(book_request.casefold() in str(pricebook_name or "").casefold())
    requested_quarter = (
        _quarter_token(book_request)
        or _quarter_token(source_level)
        or _quarter_token(question_level)
    )
    actual_quarter_token = _quarter_token(actual_quarter) or _quarter_token(pricebook_name)
    if requested_quarter:
        checks.append(bool(actual_quarter_token) and requested_quarter == actual_quarter_token)
    if checks and all(checks):
        match = "exact"
        note = f"Ценовая база совпадает с запросом: {actual_label} ({subject_label})."
    elif checks:
        match = "mismatch"
        note = (
            f"Запрошена ценовая база «{requested_label}», фактически применена "
            f"«{actual_label}» ({subject_label}). Расчёт по фактической базе не считается "
            "расчётом по запросу: подтвердите альтернативу явно — пересоберите с книгой "
            "запрошенной базы (явный аргумент pricebook) или внесите подтверждённые цены "
            "через «Внести подтверждённые данные»."
        )
    else:
        match = "unspecified"
        note = (
            f"Ценовая база в запросе и исходнике не указана; применено «{actual_label}» "
            f"({subject_label}). Подтвердите, что эта база соответствует требуемому периоду."
        )
    return {
        "requested": requested_label,
        "actual_book": str(pricebook_name or ""),
        "actual_region": actual_region,
        "actual_quarter": actual_quarter,
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
                gaps.append(
                    {
                        "resource": name if name != code else (code or name),
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
                        "action": (
                            f"Задайте цену для {name}"
                            + (f" ({code})" if code and code != name else "")
                            + (f" в позиции {position_label}" if position_label else "")
                            + (f", количество {quantity}" if quantity not in (None, "") else "")
                            + (f" {unit}" if unit else "")
                            + f". Источник: {required}."
                            + (
                                f" Проверенная ценовая база: {checked_basis}."
                                if checked_basis
                                else ""
                            )
                            + " Отсутствие цены не отменяет норму."
                        ),
                    }
                )
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
    pricebook_path = fgis_price_service.resolve_pricebook_path(
        requested_pricebook or None
    )
    pricebook = (
        fgis_price_service.get_pricebook(pricebook_path)
        if pricebook_path
        else None
    )
    pricebook_name = Path(pricebook_path).stem if pricebook_path else ""
    source_name = str(args.get("_source_name") or _source_path.name or "")
    source_text = str(args.get("_source_text") or "") or _read_source_preview_text(
        Path(_source_path)
    )
    identity = extract_lsr_source_identity(
        source_text=source_text,
        source_name=source_name,
    )
    price_basis = summarize_lsr_price_basis(
        requested_book=requested_pricebook,
        source_price_level=identity["price_level"],
        question_text=str(args.get("question") or ""),
        pricebook=pricebook,
        pricebook_name=pricebook_name,
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
    render_meta = {
        "source": source_label,
        "pricebook": pricebook_name,
        "osnovanie": identity["osnovanie"],
        "price_level": identity["price_level"],
    }
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
        "missing": missing,
        "price_gaps": collect_lsr_price_gaps(
            trace,
            pricebook=pricebook,
            pricebook_name=pricebook_name,
        ),
        "price_basis": price_basis,
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
