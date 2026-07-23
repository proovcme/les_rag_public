"""Finalize any VOR PDF from a fresh, explicit model/user decision packet.

The command never reads previous scenario revisions or cached bindings. It reparses
the source PDF, verifies its hash, applies only decisions present in the supplied
packet, resolves exact FGIS codes through the selected pricebook and writes a new
immutable revision plus an editable Appendix 3 workbook.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
from proxy.smeta_core.source_intake import intake_vor_pdf
from proxy.smeta_core.workflow import calculate_visible_rows_revision


def _load_packet(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "smeta_vor_decisions_v1":
        raise ValueError("decision packet must use schema smeta_vor_decisions_v1")
    return payload


def finalize(
    source: Path,
    decisions_path: Path,
    *,
    out_xlsx: Path,
    out_json: Path,
    book: str | None = None,
    revision_root: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    intake = intake_vor_pdf(source)
    packet = _load_packet(decisions_path)
    expected_hash = str(packet.get("source_sha256") or "").strip()
    actual_hash = str(intake.get("source_sha256") or "").strip()
    if not expected_hash or expected_hash != actual_hash:
        raise ValueError(f"decision packet source hash mismatch: expected={expected_hash!r}, actual={actual_hash!r}")

    decision_rows = packet.get("rows") if isinstance(packet.get("rows"), list) else []
    by_work: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for item in decision_rows:
        if not isinstance(item, dict):
            continue
        work_id = str(item.get("work_id") or "").strip()
        if not work_id:
            continue
        if work_id in by_work:
            duplicates.append(work_id)
            continue
        by_work[work_id] = item
    if duplicates:
        raise ValueError("duplicate decision work_id: " + ", ".join(sorted(set(duplicates))))

    source_rows = [dict(item) for item in (intake.get("work_items") or [])]
    source_ids = {str(row.get("work_id") or "") for row in source_rows}
    unknown = sorted(set(by_work) - source_ids)
    if unknown:
        raise ValueError("decision work_id not found in fresh intake: " + ", ".join(unknown))

    visible_rows: list[dict[str, Any]] = []
    for row in source_rows:
        decision = by_work.get(str(row.get("work_id") or ""), {})
        visible_rows.append({
            **row,
            "norm_code": decision.get("norm_code") or "",
            "selection_kind": decision.get("selection_kind") or "exact",
            "is_analog": bool(decision.get("is_analog", False)),
            "analog_limitations": list(decision.get("analog_limitations") or []),
            "norm_reason": decision.get("norm_reason") or decision.get("reason") or "",
            "nr_sp_rule_id": decision.get("nr_sp_rule_id") or "",
            "nr_sp_reason": decision.get("nr_sp_reason") or decision.get("reason") or "",
            "resource_bindings": list(decision.get("resource_bindings") or []),
            "covered_by_work_id": decision.get("covered_by_work_id") or "",
            "coverage_reason": decision.get("coverage_reason") or "",
        })

    trace = calculate_visible_rows_revision(
        visible_rows,
        selected_by=str(packet.get("selected_by") or "model"),
        created_by=str(packet.get("selected_by") or "model"),
        parent_revision_id="",
        change_note=f"fresh VOR finalization: {source.name}",
        revision_root=revision_root,
        book=book,
        title=str(packet.get("title") or f"Локальный сметный расчет — {source.stem}"),
    )
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    workbook_meta = {
        "stroika": "Не указано в исходном ВОР",
        "object": str(packet.get("object") or "Не указано в исходном ВОР"),
        "lsr_no": str(packet.get("lsr_no") or "1"),
        "osnovanie": source.name,
        "price_level": "2 квартал 2026 г.",
        "subject": "Санкт-Петербург",
        **(meta or {}),
    }
    render_lsr_xlsx(trace, out_xlsx, meta=workbook_meta)
    result = {
        "schema": "smeta_vor_finalization_v1",
        "zero_state": True,
        "previous_revision_read": False,
        "source": {
            "path": str(source),
            "sha256": actual_hash,
            "work_items": intake.get("work_item_count"),
        },
        "decision_packet": str(decisions_path),
        "book": book or "system_default",
        "lsr": trace,
        "xlsx_path": str(out_xlsx),
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    temp = out_json.with_suffix(out_json.suffix + ".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temp.replace(out_json)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Fresh VOR PDF -> explicit decisions -> live LSR")
    parser.add_argument("source")
    parser.add_argument("decisions")
    parser.add_argument("--out-xlsx", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--book", default="")
    parser.add_argument("--revision-root", default="")
    parser.add_argument("--stroika", default="")
    parser.add_argument("--object", default="")
    parser.add_argument("--lsr-no", default="")
    args = parser.parse_args()
    result = finalize(
        Path(args.source).expanduser().resolve(),
        Path(args.decisions).expanduser().resolve(),
        out_xlsx=Path(args.out_xlsx).expanduser().resolve(),
        out_json=Path(args.out_json).expanduser().resolve(),
        book=args.book or None,
        revision_root=args.revision_root or None,
        meta={key: value for key, value in {
            "stroika": args.stroika,
            "object": args.object,
            "lsr_no": args.lsr_no,
        }.items() if value},
    )
    summary = result.get("lsr", {}).get("summary", {})
    print(json.dumps({
        "zero_state": True,
        "result_status": summary.get("result_status"),
        "total_without_vat": summary.get("total_without_vat"),
        "vat": summary.get("vat"),
        "total_with_vat": summary.get("total_with_vat"),
        "xlsx": result.get("xlsx_path"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
