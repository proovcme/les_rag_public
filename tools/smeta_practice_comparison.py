"""Read-only comparison of exported, independently auditable smeta run JSON.

Inputs: manifest, registry[source_row], turns[turn_id, final_messages, evidence],
decisions[source_row,work_id,kind,norm_id,norm_code,quantity,turn_id,evidence_refs],
calculation[source_row,work_id,status,norm_id,quantity], xlsx[same identity,cell],
audit[source_row,operation/coverage/quantity/resources/prices,reason,source].
Evidence entries carry exact id/text and origins search/frequency/similar. Producers
must export actual final transport messages and independently read downloaded XLSX.
No selections, source data, calculators or workbook files are modified here.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

AXES = ('operation', 'coverage', 'quantity', 'resources', 'prices')
RANK = {'incorrect': 0, 'partial': 1, 'correct': 2}


def _index(rows, fields):
    indexed = {}
    for row in rows:
        key = tuple(str(row.get(f) or '') for f in fields)
        if not all(key):
            raise ValueError(f'missing identity {fields}: {key}')
        if key in indexed:
            raise ValueError(f'duplicate identity {key}')
        indexed[key] = row
    return indexed


def _same_quantity(a, b):
    try:
        left, right = Decimal(str(a)), Decimal(str(b))
        return left.is_finite() and right.is_finite() and left == right
    except InvalidOperation:
        return False


def _exact(row, other):
    # Missing canonical identity is unknown; equal display codes do not prove it.
    return bool(other and row.get('norm_id') and row['norm_id'] == other.get('norm_id')
                and _same_quantity(row.get('quantity'), other.get('quantity')))


def inspect_run(run: dict[str, Any]) -> dict[str, Any]:
    registry = _index(run['registry'], ('source_row',))
    decisions = _index(run.get('decisions', []), ('source_row', 'work_id'))
    calculation = _index(run.get('calculation', []), ('source_row', 'work_id'))
    book = _index(run.get('xlsx', []), ('source_row', 'work_id'))
    turns = _index(run.get('turns', []), ('turn_id',))
    audits = _index(run.get('audit', []), ('source_row',))
    operations = []
    for key, row in decisions.items():
        if (key[0],) not in registry:
            raise ValueError(f'decision outside registry: {key}')
        turn = turns.get((str(row.get('turn_id') or ''),), {})
        evidence = _index(turn.get('evidence', []), ('id',))
        messages = '\n'.join(str(m.get('content') or '') for m in turn.get('final_messages', []))
        refs = row.get('evidence_refs') or []
        if isinstance(refs, str):
            refs = [r.strip() for r in refs.split(',') if r.strip()]
        selected = [evidence.get((str(ref),)) for ref in refs]
        found = bool(selected) and all(e is not None for e in selected)
        shown = found and all(e.get('text') and e['text'] in messages and e['id'] in messages for e in selected)
        selected_exact = bool(shown and row.get('norm_id') and
                              any(e.get('norm_id') == row['norm_id'] for e in selected))
        origins = sorted({origin for e in selected if e for origin in e.get('origins', [])})
        calc = calculation.get(key, {})
        placed = book.get(key, {})
        calculated = calc.get('status') == 'bound' and _exact(row, calc)
        in_book = bool(placed.get('cell')) and _exact(row, placed)
        operations.append({
            'source_row': key[0], 'work_id': key[1], 'kind': row.get('kind', 'unknown'),
            'norm_code': row.get('norm_code'), 'found': found, 'shown': bool(shown),
            'selected_exact_evidence': selected_exact, 'calculated': calculated,
            'present_in_xlsx': in_book, 'chain_complete': bool(selected_exact and calculated and in_book),
            'origins': origins, 'attribution': 'mixed' if len(origins) > 1 else origins[0] if origins else 'unknown',
            'calculation_status': calc.get('status', 'unknown'), 'xlsx_cell': placed.get('cell'),
        })
    rows = []
    for (anchor,) in registry:
        audit = audits.get((anchor,), {})
        supported = bool(audit.get('source') and audit.get('reason'))
        assessment = {axis: audit.get(axis, 'unknown') if supported and audit.get(axis) in RANK else 'unknown'
                      for axis in AXES}
        rows.append({'source_row': anchor, 'audit': assessment,
                     'audit_source': audit.get('source'), 'audit_reason': audit.get('reason'),
                     'operation_ids': [r['work_id'] for r in operations if r['source_row'] == anchor]})
    kinds = Counter(r.get('kind') for r in decisions.values())
    return {
        'schema': 'les.smeta.practice-comparison.v1', 'manifest': run.get('manifest', {}),
        'counts': {'rows': len(registry), 'decided_rows': len({k[0] for k in decisions}),
                   'works': kinds['work'], 'materials': kinds['material'],
                   'resource_links': kinds['resource_in_work'],
                   'unique_norms': len({r['norm_code'] for r in decisions.values() if r.get('norm_code')})},
        'rows': rows, 'operations': operations,
        'price_states': dict(Counter(r.get('price_state', 'unknown') for r in book.values())),
        'calculation_statuses': dict(Counter(r.get('status', 'unknown') for r in calculation.values())),
        'metrics': run.get('metrics', {}),
    }


def compare_runs(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    left, right = inspect_run(baseline), inspect_run(candidate)
    a, b = ({r['source_row']: r for r in report['rows']} for report in (left, right))
    if a.keys() != b.keys():
        raise ValueError('source registries differ')
    improved, worsened, unassessed, details = [], [], [], []
    for anchor in a:
        changes = {}
        for axis in AXES:
            before, after = a[anchor]['audit'][axis], b[anchor]['audit'][axis]
            if before in RANK and after in RANK and before != after:
                changes[axis] = {'before': before, 'after': after}
        if any(RANK[c['after']] > RANK[c['before']] for c in changes.values()):
            improved.append(anchor)
        if any(RANK[c['after']] < RANK[c['before']] for c in changes.values()):
            worsened.append(anchor)
        if all(a[anchor]['audit'][x] == 'unknown' or b[anchor]['audit'][x] == 'unknown' for x in AXES):
            unassessed.append(anchor)
        if changes:
            details.append({'source_row': anchor, 'changes': changes})
    # Measured improvement alone is insufficient for accepting practice. This
    # tool deliberately leaves final acceptance to an explicit reviewed report.
    return {'schema': 'les.smeta.practice-pair.v1', 'baseline': left, 'candidate': right,
            'improved': improved, 'worsened': worsened, 'unassessed': unassessed,
            'changes': details, 'practice_accepted': False,
            'acceptance_status': 'regressions' if worsened else 'independent_acceptance_required'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.resolve() in {p.resolve() for p in (args.baseline, args.candidate) if p}:
        parser.error('output must not overwrite input')
    base = json.loads(args.baseline.read_text(encoding='utf-8'))
    result = compare_runs(base, json.loads(args.candidate.read_text(encoding='utf-8'))) if args.candidate else inspect_run(base)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
