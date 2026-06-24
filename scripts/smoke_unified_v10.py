#!/usr/bin/env python
"""Unified Construction Harness v0.10 — async-adapters smoke (offline).

Прогон через async-оркестратор: показывает adapter_statuses (parquet/lexical/vector/mail) и
searched_tiers. Offline без backend → vector/mail honest unavailable. --stub-vector/--stub-mail
демонстрируют found-путь (инжекция async-замыкания). Реальный проект: --dataset-id.

  LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1 uv run python scripts/smoke_unified_v10.py
  ... --stub-vector --stub-mail        # демо found через инжекцию
  ... --dataset-id <id> --append-ledger
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

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
    "найди ОЗК в письмах",
    "извлеки ВОР из Ф9",
    "собери предварительную ЛСР по Ф9",
    "проверь пример обсчёта",
    "что требует КАЦ",
]


def build_fixture(root: Path, ds: str = "kotelnaya") -> str:
    d = root / ds
    d.mkdir(parents=True, exist_ok=True)
    for n, sz in [("Котельная_ТМ.pdf", 5000), ("~$врем.docx", 40)]:
        (d / n).write_bytes(b"x" * sz)
    pd.DataFrame([{"наименование": "Клапан ОЗК-1", "марка": "ОЗК-1", "кол": 4, "ед": "шт"}]
                 ).to_parquet(d / "Акт_смонтированного_оборудования_ТМ.parquet")
    pd.DataFrame([{"наименование": "ОЗК клапан", "марка": "ОЗК-1", "кол": 6, "ед": "шт"}]
                 ).to_parquet(d / "Котельная_спецификация_оборудования.parquet")
    ch.write_demo_project_doc(root, dataset_id=ds)
    return ds


async def _stub_vector(q, dsids):
    return [SimpleNamespace(text="...установлен клапан ОЗК-1...", doc_name="Акт_смонтированного.pdf",
                            dataset_id="kotelnaya", chunk_ord=2, score=0.8)]


async def _stub_mail(q):
    return SimpleNamespace(items=[{"message_id": "<m1@les>", "subject": "Согласование ОЗК",
                                   "snippet": "прошу согласовать ОЗК-1"}])


async def run_one(q, *, dataset_ids, storage_root, vector_fn, mail_fn) -> dict:
    route = u.route_construction_intent(q)
    res = await u.run_unified_construction_harness_async(
        q, dataset_ids=dataset_ids, storage_root=storage_root, vector_fn=vector_fn, mail_fn=mail_fn)
    if res is None:
        return {"question": q, "route": route.intent, "status": "fell_through", "adapter_statuses": {},
                "searched_tiers": [], "sources_count": 0, "warnings": [], "failure_type": None}
    ad = res.answer_data
    return {"question": q, "route": route.intent, "source_scope": route.source_scope,
            "status": res.total_status, "adapter_statuses": ad.get("adapter_statuses", {}),
            "searched_tiers": ad.get("searched_tiers", []), "sources_count": len(res.sources or []),
            "warnings": [w[:70] for w in (res.warnings or [])][:3],
            "failure_type": _failure(ad.get("adapter_statuses", {}), res.total_status, route.intent),
            "answer": u.compose_unified_answer(res)[:160]}


def _failure(astat, status, intent):
    if status != "no_data":
        return None
    if astat.get("vector") in ("unavailable",):
        return "vector_backend_unavailable"
    if astat.get("mail") in ("unavailable",):
        return "mail_backend_not_configured"
    if intent == "norm_qa":
        return "lexical_miss"
    return "not_found"


async def amain(args) -> None:
    if args.dataset_id:
        ds, storage_root, source = args.dataset_id, (Path(args.storage_root) if args.storage_root else None), "real"
    else:
        tmp = Path(tempfile.mkdtemp())
        ds, storage_root, source = build_fixture(tmp), tmp, "fixture"
    vfn = _stub_vector if args.stub_vector else None
    mfn = _stub_mail if args.stub_mail else None
    print(f"# Unified Harness v0.10 smoke | flag={os.environ.get('LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED')} "
          f"| source={source} | vector={'stub' if vfn else 'real/none'} | mail={'stub' if mfn else 'real/none'}\n")
    results = []
    for q in CANONICAL:
        r = await run_one(q, dataset_ids=[ds], storage_root=storage_root, vector_fn=vfn, mail_fn=mfn)
        results.append(r)
        astat = " ".join(f"{k}={v}" for k, v in r["adapter_statuses"].items() if k in ("vector", "mail"))
        ft = f" [{r['failure_type']}]" if r.get("failure_type") else ""
        print(f"  [{r['route']:26s}] {r['status']:9s} {astat}{ft} | {q}")

    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"version": "v0.10", "source": source, "results": results},
                              ensure_ascii=False, indent=2))
    print(f"\nСохранено: {out} ({len(results)} кейсов)")
    if args.append_ledger:
        fails = [r for r in results if r.get("failure_type")]
        led = Path("docs/unified_harness_failure_ledger.md")
        with led.open("a", encoding="utf-8") as f:
            f.write(f"\n## append (smoke v0.10, source={source}, vector={'stub' if vfn else 'none'})\n")
            for r in fails:
                f.write(f"- `{r['failure_type']}` | {r['route']} | {r['question']}\n")
        print(f"Ledger дополнен: +{len(fails)} failure-кейсов")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-id", default=None)
    ap.add_argument("--storage-root", default=None)
    ap.add_argument("--stub-vector", action="store_true")
    ap.add_argument("--stub-mail", action="store_true")
    ap.add_argument("--output", default="artifacts/unified_v10_smoke.json")
    ap.add_argument("--append-ledger", action="store_true")
    asyncio.run(amain(ap.parse_args()))


if __name__ == "__main__":
    main()
