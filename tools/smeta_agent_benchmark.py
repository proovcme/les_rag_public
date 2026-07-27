"""Zero-state comparison of native, Qwen-Agent and Google ADK smeta loops."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from time import perf_counter
from typing import Any

from proxy.services import gesn_service
from proxy.services import smeta_chat_adapter_service as adapters
from proxy.services.smeta_agent_runner_service import (
    GoogleAdkSmetaRunner,
    QwenAgentSmetaRunner,
)
from proxy.smeta_core.document_workflow import (
    _run_global_norm_review,
    _run_native_norm_agent,
    run_vor_document_workflow,
)
from proxy.smeta_core.source_intake import intake_vor_document


QUICK_WORK_IDS = {
    "vor-0007", "vor-0010", "vor-0011", "vor-0013", "vor-0015", "vor-0016",
}


def _query_rows(source: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for index, row in enumerate(source):
        neighbors = []
        for neighbor_index in (index - 1, index + 1):
            if 0 <= neighbor_index < len(source):
                neighbor = source[neighbor_index]
                if str(neighbor.get("section") or "") == str(row.get("section") or ""):
                    neighbors.append({
                        "work_id": neighbor.get("work_id"),
                        "title": neighbor.get("title"),
                        "note": neighbor.get("note"),
                    })
        rows.append({**row, "neighbor_context": neighbors})
    return rows


def _runner(engine: str, *, allow_cloud: bool):
    if engine == "qwen_agent":
        return QwenAgentSmetaRunner(
            model=os.getenv("LES_SMETA_QWEN_MODEL", "qwen3.5:9b"),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        )
    if engine == "google_adk":
        return GoogleAdkSmetaRunner(
            api_key=os.getenv("GOOGLE_API_KEY", ""),
            model=os.getenv("LES_SMETA_GOOGLE_MODEL", "gemini-3.5-flash"),
            cloud_consent=allow_cloud,
        )
    return None


def _norm_title(selection: dict[str, Any]) -> str:
    code = str(selection.get("norm_code") or "")
    norm = gesn_service.get_norm(code, strict_family=True) if code else None
    return str((norm or {}).get("name") or "")


def evaluate_bap(result: dict[str, Any], *, full: bool) -> dict[str, Any]:
    """Dataset-specific acceptance only; never imported by the product workflow."""
    selections = result.get("selections") or {}
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, evidence: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "evidence": evidence})

    if full:
        source_ids = [
            str(row.get("work_id"))
            for row in ((result.get("intake") or {}).get("work_items") or [])
        ]
        check("all_19_source_rows", len(source_ids) == 19 and set(source_ids) == set(selections), {
            "source": len(source_ids), "mapped": len(selections),
        })
        accepted = sum(
            1 for item in selections.values()
            if item.get("norm_code") or item.get("covered_by_work_id")
        )
        check("at_least_17_bound_or_covered", accepted >= 17, accepted)
        unopened = [
            work_id for work_id, item in selections.items()
            if any(blocker.get("code") == "norm_card_not_opened" for blocker in item.get("precalculation_blockers") or [])
        ]
        check("every_bound_norm_was_opened", not unopened, unopened)
        summary = (result.get("lsr") or {}).get("summary") or {}
        check("deterministic_calculation_completed", bool(summary) and result.get("xlsx_path"), summary)
        check("vat_22_percent", float(summary.get("vat_pct") or 0.0) == 22.0, summary.get("vat_pct"))

    bap = selections.get("vor-0015") or {}
    bap_title = _norm_title(bap).casefold()
    check(
        "bap_is_not_whole_medical_luminaire",
        not bap.get("norm_code") or not ("медицин" in bap_title and "светиль" in bap_title),
        {"code": bap.get("norm_code"), "title": bap_title},
    )
    ceiling_out = selections.get("vor-0011") or {}
    ceiling_in = selections.get("vor-0012") or {}
    check(
        "ceiling_demolition_and_installation_not_same_replacement_norm",
        not ceiling_out.get("norm_code") or ceiling_out.get("norm_code") != ceiling_in.get("norm_code"),
        {"demolition": ceiling_out.get("norm_code"), "installation": ceiling_in.get("norm_code")},
    )
    paint = selections.get("vor-0013") or {}
    paint_title = _norm_title(paint).casefold()
    check(
        "ordinary_ceiling_not_unqualified_communications_collection",
        not paint.get("norm_code") or not (
            re.search(r"(?:гэснм?|ферм?)34", str(paint.get("norm_code") or "").casefold())
            and not paint.get("analog_limitations")
        ),
        {"code": paint.get("norm_code"), "title": paint_title, "limitations": paint.get("analog_limitations")},
    )
    cable = selections.get("vor-0016") or {}
    cable_title = _norm_title(cable).casefold()
    check(
        "cable_in_conduit_not_fastening_along_entire_length",
        not cable.get("norm_code") or not (
            "креплен" in cable_title and "всей длине" in cable_title
        ),
        {"code": cable.get("norm_code"), "title": cable_title},
    )
    return {
        "passed": all(item["ok"] for item in checks),
        "checks": checks,
        "professionally_accepted_rows": sum(
            1 for item in selections.values() if item.get("norm_code") or item.get("covered_by_work_id")
        ),
        "unclosed_rows": sum(
            1 for item in selections.values() if not item.get("norm_code") and not item.get("covered_by_work_id")
        ),
    }


def run(args: argparse.Namespace, engine: str) -> dict[str, Any]:
    runner = _runner(engine, allow_cloud=args.allow_cloud)
    started = perf_counter()
    progress = lambda event: print(json.dumps({
        "engine": engine,
        "phase": event.get("phase"),
        "label": event.get("label"),
    }, ensure_ascii=False), flush=True)
    configured_batch_size = getattr(args, "batch_size", None)
    if configured_batch_size is not None:
        batch_size = configured_batch_size
    elif engine == "qwen_agent":
        batch_size = 1
    elif engine == "google_adk" or args.phase == "quick":
        batch_size = 0
    else:
        batch_size = 10
    sequential_rows = engine == "qwen_agent" and batch_size == 1
    if args.phase == "quick":
        source = list(intake_vor_document(args.source).get("work_items") or [])
        rows = [row for row in _query_rows(source) if row.get("work_id") in QUICK_WORK_IDS]
        initial_result = _run_native_norm_agent(
            rows,
            adapters._smeta_document_exchange,
            mapping_exchange=adapters._smeta_document_mapping_exchange,
            candidate_limit=8,
            max_turns=args.max_turns,
            batch_size=batch_size,
            accumulate_task_state=sequential_rows,
            user_request="Собери ЛСР по исходной ВОР",
            batch_runner=runner.run_batch if runner else None,
            progress=progress,
        )
        result = _run_global_norm_review(
            rows,
            initial_result,
            adapters._smeta_document_exchange,
            mapping_exchange=adapters._smeta_document_mapping_exchange,
            candidate_limit=8,
            max_turns=args.max_turns,
            progress=progress,
            user_request="Собери ЛСР по исходной ВОР",
            batch_runner=runner.run_batch if runner else None,
        )
    else:
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", f"{engine}_{getattr(runner, 'model', 'native')}")
        result = run_vor_document_workflow(
            args.source,
            exchange=adapters._smeta_document_exchange,
            mapping_exchange=adapters._smeta_document_mapping_exchange,
            candidate_limit=12 if engine == "google_adk" else 8,
            batch_size=batch_size,
            accumulate_task_state=sequential_rows,
            require_global_review=True,
            max_agent_turns=args.max_turns,
            user_request="Собери ЛСР по исходной ВОР",
            out_xlsx=args.out_dir / f"{slug}.xlsx",
            agent_batch_runner=runner.run_batch if runner else None,
            progress=progress,
        )
    result["comparison"] = {
        "engine": engine,
        "provider": getattr(runner, "provider", "native"),
        "model": getattr(runner, "model", os.getenv("LES_SMETA_DOCUMENT_MODEL", "")),
        "phase": args.phase,
        "batch_size": batch_size,
        "task_mode": "sequential_rows" if sequential_rows else "batch",
        "elapsed_sec": round(perf_counter() - started, 2),
    }
    result["acceptance"] = evaluate_bap(result, full=args.phase == "full")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--engine", choices=("native", "qwen_agent", "google_adk", "all"), default="all")
    parser.add_argument("--phase", choices=("quick", "full"), default="quick")
    parser.add_argument("--allow-cloud", action="store_true")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument(
        "--batch-size", type=int, default=None,
        help="Rows per model task; Qwen-Agent defaults to one sequential row",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/smeta-agent-benchmark"))
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    engines = ("native", "qwen_agent", "google_adk") if args.engine == "all" else (args.engine,)
    exit_code = 0
    for engine in engines:
        result = run(args, engine)
        target = args.out_dir / f"{engine}_{args.phase}.json"
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps({
            **result["comparison"],
            "passed": result["acceptance"]["passed"],
            "report": str(target),
        }, ensure_ascii=False))
        if not result["acceptance"]["passed"]:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
