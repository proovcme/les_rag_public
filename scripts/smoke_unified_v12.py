#!/usr/bin/env python
"""Unified Construction Harness v0.12 — real-project acceptance smoke + index health.

Прогон канонических вопросов через async-оркестратор на РЕАЛЬНОМ датасете/проекте (read-only) или
фикстуре. Показывает index-health (parquet/files/lexical/mail/doc-типы), adapter_statuses, elapsed_ms.
Per-question try/except (один сбой не валит прогон). Дамп JSON + append failure-ledger.

  # фикстура
  LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1 uv run python scripts/smoke_unified_v12.py --append-ledger
  # реальный датасет рантайма (read-only)
  LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1 uv run python scripts/smoke_unified_v12.py \
    --dataset-id <ID> --storage-root /Users/ovc/LES/storage/datasets \
    --output artifacts/unified_v12_real_smoke.json --append-ledger
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "1")

import pandas as pd  # noqa: E402

from proxy.services import unified_construction_harness_service as u  # noqa: E402
from proxy.services import construction_harness_service as ch  # noqa: E402
from proxy.services import source_adapters as sa  # noqa: E402

CANONICAL = [
    "опиши проект и дай реестр документов", "выведи не мусорные документы",
    "найди ОЗК в актах смонтированного оборудования", "найди КДУ в актах",
    "найди ОЗК в спецификации", "посчитай количество ОЗК в актах",
    "правила расстановки ОЗК", "что по нормам для серверной", "нужна ли АУПТ для серверной",
    "требования к котельной по пожарке",
    "что писали по котельной в почте", "найди ОЗК в письмах",
    "извлеки ВОР из Ф9", "собери предварительную ЛСР по Ф9",
    "проверь пример обсчёта", "что требует КАЦ",
]


def build_fixture(root: Path, ds: str = "kotelnaya") -> str:
    d = root / ds
    d.mkdir(parents=True, exist_ok=True)
    for n, sz in [("Котельная_ТМ.pdf", 5000), ("~$врем.docx", 40)]:
        (d / n).write_bytes(b"x" * sz)
    pd.DataFrame([{"наименование": "Клапан ОЗК-1", "марка": "ОЗК-1", "кол": 4, "ед": "шт"}]
                 ).to_parquet(d / "Акт_смонтированного_оборудования.parquet")
    ch.write_demo_project_doc(root, dataset_id=ds)
    return ds


def _failure(status, intent, astat, health) -> str | None:
    """Классификация по INTENT в первую очередь (иначе generic-проверки мисклассифицируют:
    asbuilt-без-актов ≠ mail). v0.12-фикс."""
    if status not in ("no_data", "error"):
        return None
    if status == "error":
        return "unexpected_exception"
    hw = set()
    for d in health.get("datasets", []):
        hw |= set(d.get("warnings", []))
    if intent in ("norm_qa", "document_qa"):
        return "no_lexical_index" if "no_lexical_index" in hw else "norm_no_source"
    if intent in ("estimate_from_bor", "bor_extract", "table_agg"):
        return "f9_not_found_no_parquet" if "no_parquet" in hw else "f9_not_found"
    if intent in ("asbuilt_extract", "project_doc_entity_search", "source_scoped_entity_search"):
        return "no_source_in_scope" if "no_parquet" in hw else "term_not_found"
    if intent in ("mail_entity_search", "mail_qa"):
        return "mail_backend_not_configured" if (astat.get("mail") == "unavailable" or "no_mail_source" in hw) \
            else "mail_not_found"
    if astat.get("vector") == "unavailable":
        return "vector_unavailable"
    return "not_found"


async def run_one(q, *, dataset_ids, storage_root, health) -> dict:
    t0 = time.monotonic()
    try:
        route = u.route_construction_intent(q)
        res = await u.run_unified_construction_harness_async(
            q, dataset_ids=dataset_ids, storage_root=storage_root)
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        if res is None:
            return {"question": q, "route": route.intent, "status": "fell_through", "elapsed_ms": elapsed,
                    "adapter_statuses": {}, "searched_tiers": [], "sources_count": 0, "failure_type": None}
        ad = res.answer_data
        astat = ad.get("adapter_statuses", {})
        return {"question": q, "route": route.intent, "source_scope": route.source_scope,
                "status": res.total_status, "elapsed_ms": elapsed, "adapter_statuses": astat,
                "searched_tiers": ad.get("searched_tiers", []), "sources_count": len(res.sources or []),
                "evidence": {b.type.value: len(b.items) for b in res.evidence_blocks},
                "warnings": [w[:80] for w in (res.warnings or [])][:3],
                "failure_type": _failure(res.total_status, route.intent, astat, health),
                "answer": u.compose_unified_answer(res)[:160]}
    except Exception as e:  # noqa: BLE001 — один вопрос не валит прогон
        return {"question": q, "route": "?", "status": "error", "elapsed_ms": round((time.monotonic()-t0)*1000, 1),
                "failure_type": "unexpected_exception", "error": f"{type(e).__name__}: {str(e)[:120]}"}


async def amain(args) -> None:
    if args.dataset_id:
        ds, storage_root, source = args.dataset_id, (Path(args.storage_root) if args.storage_root else None), "real"
        dsids = [ds]
    elif args.project_id:
        from proxy.services.project_service import project_dataset_ids
        dsids = project_dataset_ids(int(args.project_id)) or []
        storage_root, source, ds = (Path(args.storage_root) if args.storage_root else None), "real_project", ",".join(dsids[:2])
    else:
        tmp = Path(tempfile.mkdtemp())
        ds, storage_root, source, dsids = build_fixture(tmp), tmp, "fixture", ["kotelnaya"]

    health = sa.inspect_dataset_index_health(dsids, storage_root=storage_root)
    print(f"# Unified Harness v0.12 smoke | source={source} | datasets={len(dsids)}")
    for d in health["datasets"]:
        print(f"  health[{d['dataset_id'][:8]}] parquet={d['parquet_count']} md={d.get('md_file_count',0)} eml={d.get('eml_file_count',0)} md_tbl={d.get('markdown_table_count',0)} "
              f"mail={d['mail_count']} lex={d['lexical_chunk_count']} warns={d['warnings']}")
    print()
    questions = CANONICAL
    if args.questions_file and Path(args.questions_file).exists():
        questions = [ln.strip() for ln in Path(args.questions_file).read_text().splitlines() if ln.strip()]

    results = []
    for q in questions:
        r = await run_one(q, dataset_ids=dsids, storage_root=storage_root, health=health)
        results.append(r)
        ft = f" [{r['failure_type']}]" if r.get("failure_type") else ""
        print(f"  [{r['route']:24s}] {r['status']:9s} {r.get('elapsed_ms', 0):>6}ms src={r.get('sources_count', 0)}{ft} | {q}")

    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"version": "v0.12", "source": source, "datasets": dsids,
                               "index_health": health, "results": results}, ensure_ascii=False, indent=2))
    fails = [r for r in results if r.get("failure_type")]
    print(f"\nСохранено: {out} | {len(results)} кейсов, {len(fails)} failure")
    if args.append_ledger:
        from collections import Counter
        cats = Counter(r["failure_type"] for r in fails)
        led = Path("docs/unified_harness_failure_ledger.md")
        with led.open("a", encoding="utf-8") as f:
            f.write(f"\n## append (smoke v0.12, source={source}, datasets={len(dsids)})\n")
            f.write(f"кейсов: {len(results)}, failure: {len(fails)} | категории: {dict(cats)}\n")
            for r in fails:
                f.write(f"- `{r['failure_type']}` | {r['route']} | {r['question']}\n")
        print(f"Ledger дополнен: +{len(fails)} ({dict(cats)})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-id", default=None)
    ap.add_argument("--project-id", default=None)
    ap.add_argument("--storage-root", default=None)
    ap.add_argument("--questions-file", default=None)
    ap.add_argument("--output", default="artifacts/unified_v12_smoke.json")
    ap.add_argument("--append-ledger", action="store_true")
    asyncio.run(amain(ap.parse_args()))


if __name__ == "__main__":
    main()
