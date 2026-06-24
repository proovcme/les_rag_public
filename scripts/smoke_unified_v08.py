#!/usr/bin/env python
"""Unified Construction Harness v0.8 — operational smoke (offline, без облака).

Поднимает фикстуру проекта «котельная» (документы + акты + Ф9/ВОР + спецификация + мусор), включает
флаг и прогоняет канонические вопросы через unified-harness, печатает route/status/sources/blockers/
ответ/trace и сохраняет в artifacts/unified_v08_smoke.json. Resource-обсчёт — на РЕАЛЬНОМ workbook.

Запуск:  LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1 uv run python scripts/smoke_unified_v08.py
Флаг OFF по умолчанию; скрипт сам ставит его для прогона. Реальный проект: --dataset-id <ds>.
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

QUESTIONS = [
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
    ch.write_demo_project_doc(root, dataset_id=ds)        # Ф9/ВОР parquet
    return ds


def run(question: str, *, dataset_ids, storage_root) -> dict:
    route = u.route_construction_intent(question)
    res = u.run_unified_construction_harness(question, dataset_ids=dataset_ids, storage_root=storage_root)
    if res is None:
        return {"question": question, "route": route.intent, "status": "fell_through_to_old_path",
                "sources": 0, "blockers": [], "answer": "(не unified intent → старый RAG-путь)"}
    blockers = [b for blk in res.evidence_blocks for it in blk.items for b in it.blockers]
    ev = {b.type.value: len(b.items) for b in res.evidence_blocks}
    return {"question": question, "route": route.intent, "source_scope": route.source_scope,
            "route_source": route.route_source, "status": res.total_status,
            "provenance": res.answer_data.get("provenance", ""), "sources": len(res.sources or []),
            "evidence": ev, "blockers": blockers[:3], "final_total": res.final_total,
            "answer": u.compose_unified_answer(res)[:240]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-id", default=None, help="реальный датасет (иначе fixture котельная)")
    ap.add_argument("--storage-root", default=None, help="storage root реального проекта")
    args = ap.parse_args()

    if args.dataset_id:
        ds, storage_root = args.dataset_id, (Path(args.storage_root) if args.storage_root else None)
        tmp = None
    else:
        tmp = Path(tempfile.mkdtemp())
        ds, storage_root = build_fixture(tmp), tmp

    print(f"# Unified Harness v0.8 smoke | flag={os.environ.get('LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED')} "
          f"| dataset={ds} | source={'fixture' if tmp else 'real'}\n")
    results = []
    for q in QUESTIONS:
        r = run(q, dataset_ids=[ds], storage_root=storage_root)
        results.append(r)
        print(f"  [{r['route']:26s}] {r['status']:9s} src={r['sources']:<2} "
              f"blk={len(r['blockers'])} | {q}")

    out = Path("artifacts"); out.mkdir(exist_ok=True)
    payload = {"flag": os.environ.get("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED"),
               "dataset": ds, "source": "fixture" if tmp else "real", "results": results}
    (out / "unified_v08_smoke.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nСохранено: artifacts/unified_v08_smoke.json ({len(results)} кейсов)")


if __name__ == "__main__":
    main()
