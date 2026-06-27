#!/usr/bin/env python
"""v0.16 §8 — smoke: инвентарь → (dry-run извлечения) → канонические вопросы через unified harness →
extraction-state. Опц. append-ledger. БЕЗ записи sidecar (dry-run), БЕЗ OCR, БЕЗ Qdrant-эмбеддинга.

  LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1 python scripts/smoke_unified_v16.py \
    --dataset-id <ID> --storage-root /Users/ovc/LES/storage/datasets \
    --use-existing-sidecars --output artifacts/unified_v16_smoke_<ID>.json --append-ledger
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from proxy.services import sidecar_ops_service as ops
from proxy.services import doc_extract_service as de
from proxy.services import unified_construction_harness_service as u
from proxy.services.evidence_contract import EvidenceType

CANONICAL = [
    "опиши проект и дай реестр документов", "выведи не мусорные документы",
    "найди ОЗК в актах смонтированного оборудования", "найди КДУ в актах",
    "найди ШУ-1 в исполнительной", "найди ОЗК в спецификации", "правила расстановки ОЗК",
    "что по нормам для серверной", "нужна ли АУПТ для серверной",
    "что писали по котельной в почте", "найди ОЗК в письмах", "извлеки ВОР из Ф9",
    "собери предварительную ЛСР по Ф9", "проверь пример обсчёта", "что требует КАЦ",
]


def run(dataset_id: str, *, storage_root: Path, questions: list[str], dry_run_extraction: bool,
        index_dry: bool) -> dict:
    inv = ops.inspect_dataset(storage_root / dataset_id, storage_root=storage_root)
    sidecar_available = inv["sidecar_count"] > 0
    is_eml = inv["eml_count"] > 0
    out = {"version": "unified_v16", "dataset_id": dataset_id, "inventory": inv,
           "sidecar_available": sidecar_available, "results": []}
    if dry_run_extraction:
        out["extraction_dry_run"] = "would_extract=%d (sidecar=%d)" % (inv["extractable_count"], inv["sidecar_count"])
    if index_dry:
        out["lexical_index_dry_run"] = ops.lexical_index_extracted(dataset_id, storage_root=storage_root, dry_run=True)
    out["ocr"] = ops.ocr_detection(dataset_id, storage_root=storage_root)
    for q in questions:
        r = u.run_unified_construction_harness(q, dataset_ids=[dataset_id], storage_root=storage_root)
        if r is None:   # harness не маршрутизировал вопрос (не его контур) → фиксируем как unrouted
            out["results"].append({"q": q, "status": "unrouted", "tiers": [], "sources": 0,
                                   "source_ref": None, "extraction_state": "not_construction_intent"})
            continue
        retr = [it.source_refs[0] for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED
                for it in b.items if it.source_refs]
        msg = ops.extraction_state_message(
            sidecar_available=sidecar_available, has_extractable_docs=inv["extractable_count"] > 0,
            is_runtime=de.is_runtime_path(storage_root), write_allowed=de.runtime_write_allowed(),
            stale_count=inv["stale_count"], no_text_layer_count=out["ocr"]["pdf_no_text_layer_count"],
            term_searched="extracted_body" in r.answer_data.get("searched_tiers", []),
            term_found=r.total_status == "complete", is_eml_dataset=is_eml)
        out["results"].append({"q": q, "status": r.total_status,
                               "tiers": r.answer_data.get("searched_tiers", []),
                               "sources": len(r.sources or []), "source_ref": (retr[:1] or [None])[0],
                               "extraction_state": msg["case"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-id", required=True)
    ap.add_argument("--project-id", type=int, default=0)
    ap.add_argument("--storage-root", default="storage/datasets")
    ap.add_argument("--output", default=None)
    ap.add_argument("--append-ledger", action="store_true")
    ap.add_argument("--dry-run-extraction", action="store_true")
    ap.add_argument("--use-existing-sidecars", action="store_true")
    ap.add_argument("--index-sidecars-dry-run", action="store_true")
    ap.add_argument("--questions-file", default=None)
    args = ap.parse_args()
    qs = CANONICAL
    if args.questions_file:
        qs = [l.strip() for l in Path(args.questions_file).read_text().splitlines() if l.strip()]
    rep = run(args.dataset_id, storage_root=Path(args.storage_root), questions=qs,
              dry_run_extraction=args.dry_run_extraction, index_dry=args.index_sidecars_dry_run)
    print(f"# smoke v16 | {args.dataset_id} | sidecar={rep['sidecar_available']} guess={rep['inventory']['corpus_guess']}")
    for r in rep["results"]:
        sr = (r["source_ref"] or "").split("/")[-1][:42]
        print(f"  {r['status']:9s} [{r['extraction_state']:32s}] {r['q'][:34]:34s} {sr}")
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
        print(f"Отчёт: {out}")
    if args.append_ledger:
        led = Path("docs/unified_harness_failure_ledger.md")
        states = sorted({r["extraction_state"] for r in rep["results"]})
        line = (f"\n- smoke v16 `{args.dataset_id}`: corpus={rep['inventory']['corpus_guess']} "
                f"sidecar={rep['sidecar_available']} states={states} "
                f"complete={sum(1 for r in rep['results'] if r['status']=='complete')}/{len(rep['results'])}\n")
        led.write_text(led.read_text() + line)
        print(f"Ledger += {led}")


if __name__ == "__main__":
    main()
