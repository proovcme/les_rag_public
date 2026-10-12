"""Account for the verified source file independently of model decisions."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from proxy.services.tabular_attachment_service import format_tabular_attachment_context
from proxy.smeta_core.row_decision import aggregate_operation_statuses
from proxy.smeta_core.vor_rows import decision_anchor, row_anchor, rows_from_attachment_text


def attach_source_registry(trace: dict[str, Any], source: Path) -> None:
    """Add source inventory/statuses without inserting or changing model decisions."""
    context = format_tabular_attachment_context(
        source, source.name, max_chars=None, max_cell_chars=None,
    ) if source.is_file() else None
    rows = rows_from_attachment_text(context[0]) if context else []
    summary = trace.setdefault('summary', {})
    if not rows:
        trace['source_registry'] = {'status': 'unavailable', 'rows': []}
        flags = ['SOURCE_REGISTRY_UNAVAILABLE']
    else:
        anchors = [row_anchor(row) for row in rows]
        by_anchor: dict[str, list[dict[str, Any]]] = {}
        flags = []
        for item in trace.get('row_bindings') or []:
            anchor = decision_anchor({'source_row': item.get('row')}, anchors)
            if not anchor:
                flags.append(f"source_binding_unresolved:{item.get('row')}:{item.get('work_id') or ''}")
                continue
            by_anchor.setdefault(anchor, []).append(item)
        registry = []
        for row in rows:
            anchor = row_anchor(row)
            bindings = by_anchor.get(anchor, [])
            statuses = aggregate_operation_statuses([
                {'source_row': anchor, 'work_id': b.get('work_id'), 'status': b.get('status')}
                for b in bindings
            ])
            status = ((statuses or {}).get(anchor) or 'operation_identity_conflict') if bindings else 'not_processed'
            registry.append({**row, 'status': status,
                             'work_ids': [str(b.get('work_id') or '') for b in bindings]})
            if not bindings:
                flags.append(f'source:{anchor}:not_processed')
        trace['source_registry'] = {'status': 'parsed', 'rows': registry}
        from proxy.smeta_core.row_decision import row_accounted, source_resolved

        bound = sum(row_accounted(r['status']) for r in registry)
        resolved = sum(source_resolved(r['status']) for r in registry)
        summary.update(source_rows=len(registry), input_rows=len(registry), bound_rows=bound,
                       non_work_rows=sum(r['status'] == 'section_recognized' for r in registry),
                       resolved_source_rows=resolved,
                       unbound_rows=len(registry)-resolved, open_rows=len(registry)-resolved,
                       not_processed_rows=sum(r['status'] == 'not_processed' for r in registry))
    if flags:
        summary['flags'] = list(summary.get('flags') or []) + flags
        summary.update(full_amount=None, amount_status='partial')
        if summary.get('result_status') == 'priced_final':
            summary['result_status'] = 'priced_partial'
        trace.setdefault('warnings', []).extend(flags)
