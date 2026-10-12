"""Thin LSR workbook adapter for decisions already made by the chat model.

The adapter performs no retrieval and never selects a norm. It binds the
model-provided norm codes to exact local cards, calculates the resulting trace,
and renders that trace to XLSX.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Mapping

from proxy.services import fgis_price_service
from proxy.services.rim_lsr_trace_service import build_lsr_trace_from_visible_rows
from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
from proxy.services.smeta_source_registry_service import attach_source_registry


async def build_lsr_workbook_from_decisions(
    source_path: Path,
    args: Mapping[str, Any],
    output_path: Path,
    progress: Callable[[str, int, int | None], None],
) -> Mapping[str, Any]:
    """Calculate and render the model's explicit LSR row decisions."""
    decisions = [dict(item) for item in (args.get("decisions") or [])]
    requested_pricebook = str(
        args.get("pricebook") or args.get("pricebook_id") or ""
    ).strip()
    document_basis = args.get('_document_price_basis')
    price_problem = None
    if document_basis is not None:
        pricebook_path = document_basis.get('path')
        try:
            pricebook = fgis_price_service.pricebook_for_basis(document_basis)
        except fgis_price_service.PriceBookRevisionConflict as error:
            pricebook = None
            price_problem = dict(reason=error.reason, expected=error.expected, actual=error.actual)
    else:
        pricebook_path = fgis_price_service.resolve_pricebook_path(requested_pricebook or None)
        pricebook = fgis_price_service.get_pricebook(pricebook_path) if pricebook_path else None
    pricebook_name = Path(pricebook_path).stem if pricebook_path else ""
    source_name = Path(str(args.get("_source_name") or "")).name
    workbook_title = "Локальный сметный расчёт" + (f" по {source_name}" if source_name else "")
    progress("model_decisions", 0, len(decisions))
    trace = await asyncio.to_thread(
        build_lsr_trace_from_visible_rows,
        decisions,
        pricebook=pricebook,
        name=workbook_title,
        document_price_basis=document_basis,
    )
    if price_problem:
        trace['price_basis_conflict'] = price_problem
        summary = trace['summary']
        summary.update(result_status='price_basis_conflict', full_amount=None, amount_status='partial')
        summary.setdefault('flags', []).append('price_basis_conflict: ' + price_problem['reason'])
    from proxy.smeta_core.calculation_receipt import calculation_receipts, apply_model_review
    receipts = calculation_receipts(trace, pricebook=pricebook, pricebook_name=pricebook_name)
    if args.get('review_calculation'):
        apply_model_review(trace, receipts, decisions)
    if price_problem:
        trace['summary']['result_status'] = 'price_basis_conflict'
    await asyncio.to_thread(attach_source_registry, trace, source_path)
    render_meta = {
        "source": source_name,
        "osnovanie": source_name or "—",
        "pricebook": pricebook_name,
        "document_price_basis": document_basis,
    }
    if pricebook is not None:
        render_meta.update(
            {
                "subject": str(getattr(pricebook, "region", "") or "Не указан"),
                "price_level": str(
                    getattr(pricebook, "quarter", "") or
                    ("Не указан" if document_basis is not None else pricebook_name)
                ),
            }
        )
    await asyncio.to_thread(
        render_lsr_xlsx,
        trace,
        output_path,
        title=workbook_title,
        meta=render_meta,
    )
    progress("model_decisions", len(decisions), len(decisions))

    from proxy.smeta_core.row_decision import decision_resolved

    bindings = list(trace.get("row_bindings") or [])
    missing = [
        f"row:{binding.get('row')}:{binding.get('status') or 'unresolved'}"
        for binding in bindings
        if not decision_resolved(binding.get("status"))
    ]
    # Связанная строка тоже может требовать проверки. Предложенный моделью коэффициент
    # в расчёт не принимается без основания, и молчать об этом нельзя: строка попадёт
    # в смету по норме, а человек не узнает, что модель считала нужным её поднять
    # (ревью Codex 11.09).
    missing.extend(
        f"row:{binding.get('row')}:coefficient_needs_basis"
        for binding in bindings
        if str(binding.get("coefficient_status") or "") == "needs_basis"
        and binding.get("status") != "coefficient_basis_required"
    )
    missing.extend(str(flag) for flag in (trace.get('summary') or {}).get('flags') or [])
    bound_rows = int((trace.get("summary") or {}).get("bound_rows") or 0)
    return {
        "file_path": output_path,
        "source_rows": int((trace.get("summary") or {}).get("source_rows", len({
            str(row.get("source_row") or index) for index, row in enumerate(decisions, 1)}))),
        "pricebook": pricebook_name,
        "document_price_basis": document_basis,
        "price_basis_conflict": price_problem,
        "pricing_status": str((trace.get("summary") or {}).get("result_status") or ""),
        "missing": missing,
        # Сколько строк расчёт действительно связал. Без этого числа измерение успеха
        # подменялось арифметикой «выбрано минус отвергнуто» (ревью Codex 11.09).
        "bound_rows": bound_rows,
        "row_calculation": receipts,
        "blockers": ([] if bound_rows else ["NO_BOUND_LSR_ROWS"]),
    }
