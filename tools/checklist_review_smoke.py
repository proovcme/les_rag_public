#!/usr/bin/env python3
"""Smoke-CLI для checklist_review_service (T2.2).

Тонкая обёртка над `proxy.services.checklist_review_service.run_checklist_review` с реальными
default-провайдерами (`default_inventory_provider`/`default_search_provider`/
`default_workbook_provider` — MetaDB sqlite + lexical_index_service, см. implementation_plan.md
§2-§4). НЕ подставляет фейки — прогон предполагается против живого датасета LES.

ВНИМАНИЕ (T2.2, промпт): этот скрипт НЕ запускается против живой системы в рамках T2.2 —
индексация датасета ПД_О ещё идёт на момент написания. Гейт T2.2 — только `compileall`
(синтаксическая корректность), реальный прогон — задача T2.3 (см. docs/SESSION_LOG.md, следующий
шаг), после завершения индексации, на датасете ПД_О (id 3904e76a-7adf-49c1-918c-d7dbfe44a3f2).

Использование (T2.3+):
    uv run python tools/checklist_review_smoke.py \
        --dataset-id 3904e76a-7adf-49c1-918c-d7dbfe44a3f2 \
        --template glorax_pd_2026 \
        --discipline АР \
        --limit 20 \
        --out storage/checklist_review/smoke_report.json

Печатает summary.by_status/by_kind в консоль + топ-10 items (по item_id, для быстрого
визуального контроля); `--out PATH` дополнительно пишет полный `checklist_review_v1`
результат на диск (ensure_ascii=False, indent=2).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proxy.services.checklist_review_service import (  # noqa: E402
    default_inventory_provider,
    default_search_provider,
    default_workbook_provider,
    load_checklist_template,
    run_checklist_review,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True, help="dataset_id комплекта ПД/РД в LES")
    parser.add_argument(
        "--template", default="glorax_pd_2026", help="Имя template'а (config/checklists/{name}.json)"
    )
    parser.add_argument(
        "--discipline", default=None, help="Фильтр по дисциплине (напр. АР); по умолчанию — все"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Ограничить число обрабатываемых items template'а (весь template, если не задано)",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Путь для сохранения полного JSON-отчёта (checklist_review_v1); без флага — только stdout",
    )
    return parser.parse_args(argv)


def _truncate_template(template: dict, limit: int | None) -> dict:
    """Ограничивает число items template'а до `limit` (порядок сохраняется, остальные поля
    template'а — name/stage/disciplines и т.п. — не трогаются)."""
    if limit is None or limit <= 0:
        return template
    truncated = dict(template)
    truncated["items"] = list(template.get("items", []))[:limit]
    return truncated


def _print_summary(result: dict) -> None:
    summary = result["summary"]
    print(f"template={result['template']} stage={result['stage']} dataset_id={result['dataset_id']} "
          f"discipline={result['discipline']}")
    print(f"total={summary['total']} source_backed={summary['source_backed']} "
          f"without_evidence={summary['without_evidence']}")

    print("\nby_status:")
    for status, count in sorted(summary["by_status"].items(), key=lambda kv: -kv[1]):
        print(f"  {status:<22} {count}")

    print("\nby_kind:")
    for kind, count in sorted(summary["by_kind"].items(), key=lambda kv: -kv[1]):
        print(f"  {kind:<16} {count}")

    print("\nsuggested:")
    for answer, count in summary["suggested"].items():
        print(f"  {answer:<16} {count}")


def _print_top_items(result: dict, top_n: int = 10) -> None:
    items = result["items"][:top_n]
    if not items:
        return
    print(f"\nтоп-{len(items)} items (evidence кратко):")
    for it in items:
        criterion = it["criterion"]
        if len(criterion) > 70:
            criterion = criterion[:67] + "..."
        evidence = it.get("document_evidence") or []
        ev_summary = f"{evidence[0].get('kind', '')}:{evidence[0].get('source_ref', '')}" if evidence else "—"
        print(f"  [{it['item_id']}] {it['status']:<20} suggested={it['suggested_answer']:<15} "
              f"evidence={ev_summary} {criterion}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    template = load_checklist_template(args.template)
    template = _truncate_template(template, args.limit)

    from proxy.services.checklist_review_service import default_pp87_config_provider

    result = run_checklist_review(
        template,
        dataset_id=args.dataset_id,
        discipline=args.discipline,
        inventory_provider=default_inventory_provider,
        search_provider=default_search_provider,
        workbook_provider=default_workbook_provider,
        pp87_config=default_pp87_config_provider(),
    )

    _print_summary(result)
    _print_top_items(result)

    comp = result.get("pp87_composition")
    if comp:
        print("\nСостав ПД по ПП РФ №87:")
        for sec in comp.get("sections", []):
            mark = {"present": "+", "missing": "!", "unknown": "?"}.get(sec.get("status"), "?")
            print(f"  [{mark}] {sec.get('code'):<6} {sec.get('status'):<8} {sec.get('title', '')[:60]} "
                  f"(files: {len(sec.get('matched_files', []))})")

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"\nOK: полный результат записан в {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
