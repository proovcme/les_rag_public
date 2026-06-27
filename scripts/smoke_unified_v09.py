#!/usr/bin/env python
"""Unified Construction Harness v0.9 — operational smoke + failure-ledger harvest (offline).

Прогон канонических вопросов через unified-harness с трекингом searched_tiers и adapter-warnings.
Дамп machine-readable artifact + опциональный append в failure-ledger. Реальный проект: --dataset-id.

Запуск (fixture):
  LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1 uv run python scripts/smoke_unified_v09.py
Реальный проект (НЕ трогает /Users/ovc/LES/.env — флаг в env процесса):
  LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1 uv run python scripts/smoke_unified_v09.py \
    --dataset-id <id> --storage-root <path> --output artifacts/unified_v09_smoke.json --append-ledger
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "1")

import pandas as pd  # noqa: E402

from proxy.services import unified_construction_harness_service as u  # noqa: E402
from proxy.services import construction_harness_service as ch  # noqa: E402

CANONICAL = [
    "опиши проект котельная и дай реестр документов",
    "найди ОЗК в актах смонтированного оборудования",
    "найди КДУ в актах смонтированного оборудования",
    "найди ОЗК в спецификации",
    "правила расстановки ОЗК",
    "что писали по котельной в почте",
    "извлеки ВОР из Ф9",
    "собери предварительную ЛСР по Ф9",
    "проверь пример обсчёта",
    "что требует КАЦ",
]

# ожидаемый источник по intent'у → для классификации failure_type
_NEEDS_SCOPE = {"project_document_registry", "project_summary", "estimate_from_bor", "bor_extract",
                "table_agg", "asbuilt_extract", "mail_entity_search", "project_doc_entity_search"}


def build_fixture(root: Path, ds: str = "kotelnaya") -> str:
    d = root / ds
    d.mkdir(parents=True, exist_ok=True)
    for n, sz in [("Котельная_тепломеханика_ТМ.pdf", 5000), ("Котельная_газоснабжение_ГСВ.pdf", 4000),
                  ("Котельная_АУПТ_ППА.docx", 3000), ("~$врем.docx", 40), ("копия_old.pdf", 2000)]:
        (d / n).write_bytes(b"x" * sz)
    pd.DataFrame([{"акт": "А-12", "наименование": "Клапан огнезадерживающий ОЗК-1", "марка": "ОЗК-1",
                   "кол": 4, "ед": "шт", "помещение": "венткамера №3"}]
                 ).to_parquet(d / "Акт_смонтированного_оборудования_ТМ.parquet")
    pd.DataFrame([{"наименование": "ОЗК огнезадерживающий клапан", "марка": "ОЗК-1", "кол": 6, "ед": "шт"}]
                 ).to_parquet(d / "Котельная_спецификация_оборудования.parquet")
    ch.write_demo_project_doc(root, dataset_id=ds)
    return ds


def _failure_type(intent: str, status: str, warns: list[str]) -> str | None:
    if status not in ("no_data",):
        return None                              # complete/partial — не провал
    wl = " ".join(warns).lower()
    if "mail_backend_not_configured" in wl:
        return "mail_backend_not_configured"
    if "vector_unavailable" in wl:
        return "vector_unavailable"
    if "lexical_unavailable" in wl:
        return "lexical_unavailable"
    if intent == "norm_qa":
        return "lexical_miss"
    if intent in _NEEDS_SCOPE:
        return "term_or_source_not_found"
    return "no_data"


def run_one(q: str, *, dataset_ids, storage_root) -> dict:
    route = u.route_construction_intent(q)
    res = u.run_unified_construction_harness(q, dataset_ids=dataset_ids, storage_root=storage_root)
    if res is None:
        return {"question": q, "route": route.intent, "status": "fell_through_to_old_path",
                "sources_count": 0, "blockers": [], "searched_tiers": [], "warnings": [],
                "failure_type": None, "answer": "(не unified intent → старый RAG)"}
    ad = res.answer_data
    blockers = [b for blk in res.evidence_blocks for it in blk.items for b in it.blockers][:3]
    warns = list(res.warnings or [])
    return {"question": q, "route": route.intent, "source_scope": route.source_scope,
            "status": res.total_status, "provenance": ad.get("provenance", ""),
            "sources_count": len(res.sources or []),
            "evidence": {b.type.value: len(b.items) for b in res.evidence_blocks},
            "searched_tiers": ad.get("searched_tiers", []), "blockers": blockers, "warnings": warns,
            "failure_type": _failure_type(route.intent, res.total_status, warns),
            "trace_version": "unified_construction_harness_v0_9",
            "answer": u.compose_unified_answer(res)[:200]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-id", default=None)
    ap.add_argument("--storage-root", default=None)
    ap.add_argument("--questions-file", default=None, help="txt, по вопросу на строку")
    ap.add_argument("--output", default="artifacts/unified_v09_smoke.json")
    ap.add_argument("--append-ledger", action="store_true")
    args = ap.parse_args()

    questions = CANONICAL
    if args.questions_file and Path(args.questions_file).exists():
        questions = [ln.strip() for ln in Path(args.questions_file).read_text().splitlines() if ln.strip()]

    if args.dataset_id:
        ds, storage_root, source = args.dataset_id, (Path(args.storage_root) if args.storage_root else None), "real"
    else:
        tmp = Path(tempfile.mkdtemp())
        ds, storage_root, source = build_fixture(tmp), tmp, "fixture"

    print(f"# Unified Harness v0.9 smoke | flag={os.environ.get('LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED')} "
          f"| dataset={ds} | source={source}\n")
    results = [run_one(q, dataset_ids=[ds], storage_root=storage_root) for q in questions]
    for r in results:
        ft = f" [{r['failure_type']}]" if r.get("failure_type") else ""
        print(f"  [{r['route']:26s}] {r['status']:9s} src={r['sources_count']:<2} "
              f"tiers={len(r.get('searched_tiers', []))}{ft} | {r['question']}")

    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": "v0.9", "source": source, "dataset": ds, "results": results}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nСохранено: {out} ({len(results)} кейсов)")

    if args.append_ledger:
        fails = [r for r in results if r.get("failure_type")]
        led = Path("docs/unified_harness_failure_ledger.md")
        with led.open("a", encoding="utf-8") as f:
            f.write(f"\n## append (smoke v0.9, source={source}, dataset={ds})\n")
            f.write(f"маршрутов: {len(results)}, failure-кейсов: {len(fails)}\n")
            for r in fails:
                f.write(f"- `{r['failure_type']}` | {r['route']} | {r['question']}\n")
        print(f"Ledger дополнен: {led} (+{len(fails)} failure-кейсов)")


if __name__ == "__main__":
    main()
