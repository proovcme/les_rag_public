"""Thin LSR workbook adapter for decisions already made by the chat model.

The adapter performs no retrieval and never selects a norm. It binds the
model-provided norm codes to exact local cards, calculates the resulting trace,
and renders that trace to XLSX.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Mapping

from proxy.services.rim_lsr_trace_service import build_lsr_trace_from_visible_rows
from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx


async def build_lsr_workbook_from_decisions(
    _source_path: Path,
    args: Mapping[str, Any],
    output_path: Path,
    progress: Callable[[str, int, int | None], None],
) -> Mapping[str, Any]:
    """Calculate and render the model's explicit LSR row decisions."""
    decisions = [dict(item) for item in (args.get("decisions") or [])]
    progress("model_decisions", 0, len(decisions))
    trace = await asyncio.to_thread(
        build_lsr_trace_from_visible_rows,
        decisions,
        name=str(args.get("question") or "Локальный сметный расчёт"),
    )
    await asyncio.to_thread(
        render_lsr_xlsx,
        trace,
        output_path,
        title=str(args.get("question") or "Локальный сметный расчёт"),
        meta={"source": str(args.get("_source_name") or "")},
    )
    progress("model_decisions", len(decisions), len(decisions))

    bindings = list(trace.get("row_bindings") or [])
    missing = [
        f"row:{binding.get('row')}:{binding.get('status') or 'unresolved'}"
        for binding in bindings
        if str(binding.get("status") or "") != "bound"
    ]
    bound_rows = int((trace.get("summary") or {}).get("bound_rows") or 0)
    return {
        "file_path": output_path,
        "source_rows": len(decisions),
        "missing": missing,
        "blockers": ([] if bound_rows else ["NO_BOUND_LSR_ROWS"]),
    }
