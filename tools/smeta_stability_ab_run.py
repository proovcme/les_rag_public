"""Run document LSR stability / A/B local measurements (diagnostic only).

Does not choose norms. Loads config/local/windows-cuda.env, runs
smeta_document_local_run-compatible workflow via adapters, writes metrics JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ[key] = val


def _metrics_from_report(report: dict[str, Any], *, elapsed_sec: float, model: str) -> dict[str, Any]:
    selections = report.get("selections") or {}
    counts: Counter[str] = Counter()
    for selection in selections.values():
        if not isinstance(selection, dict):
            counts["other"] += 1
            continue
        status = str(selection.get("review_status") or "")
        if str(selection.get("norm_code") or "").strip() and status != "model_batch_candidate":
            counts["bound"] += 1
        elif status == "model_batch_candidate":
            counts["candidate"] += 1
        elif status in {"model_batch_unbound", "model_batch_open"}:
            counts[status.replace("model_batch_", "")] += 1
        elif not str(selection.get("norm_code") or "").strip():
            counts["open"] += 1
        else:
            counts["other"] += 1
    summary = ((report.get("lsr") or {}).get("summary") or {})
    agent = report.get("agent_trace") or {}
    return {
        "model": model,
        "elapsed_sec": round(elapsed_sec, 1),
        "input_rows": summary.get("input_rows") or len(selections),
        "bound_rows": int(counts.get("bound") or 0),
        "unbound_rows": int(counts.get("unbound") or 0),
        "candidate_rows": int(counts.get("candidate") or 0),
        "open_rows": int(counts.get("open") or 0),
        "result_status": summary.get("result_status"),
        "agent_status": agent.get("status"),
        "incomplete_blocker": (report.get("incomplete_blocker") or {}).get("code"),
        "xlsx_path": report.get("xlsx_path"),
        "hard_fail": False,
        "counts": dict(counts),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("storage/stability_runs"))
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path("config/local/windows-cuda.env"),
    )
    args = parser.parse_args(argv)

    _load_env_file(args.env_file.resolve())
    os.environ["LES_SMETA_DOCUMENT_PROVIDER"] = "ollama"
    os.environ["LES_SMETA_DOCUMENT_MODEL"] = args.model
    os.environ["OLLAMA_MODEL"] = args.model
    os.environ["LES_OLLAMA_MODEL"] = args.model
    os.environ.setdefault("LES_SMETA_DOCUMENT_BATCH_SIZE", str(args.batch_size))

    from proxy.services import smeta_chat_adapter_service as adapters
    from proxy.smeta_core.document_workflow import run_vor_document_workflow

    source = args.source.resolve()
    out_dir = (args.out_dir / args.label).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = source.stem.replace(" ", "_")[:80]
    xlsx_path = out_dir / f"{stem}.lsr.xlsx"
    report_path = out_dir / f"{stem}.report.json"
    metrics_path = out_dir / "metrics.json"

    started = time.monotonic()
    print(f"label={args.label} model={args.model} source={source}", flush=True)
    try:
        workflow = run_vor_document_workflow(
            source,
            exchange=adapters._smeta_document_exchange,
            mapping_exchange=adapters._smeta_document_mapping_exchange,
            candidate_limit=8,
            out_xlsx=xlsx_path,
            out_report=report_path,
            progress=lambda event: print(
                f"[{time.monotonic() - started:7.1f}s] "
                f"{event.get('phase')} {event.get('label') or event.get('status')}",
                flush=True,
            ),
            source_name=source.name,
            user_request="Собери первую ЛСР по приложенной ВОР",
            batch_size=args.batch_size,
            max_agent_turns=args.max_turns,
            require_scoped_search=True,
            require_global_review=False,
        )
        elapsed = time.monotonic() - started
        metrics = _metrics_from_report(workflow, elapsed_sec=elapsed, model=args.model)
    except Exception as error:
        elapsed = time.monotonic() - started
        metrics = {
            "model": args.model,
            "elapsed_sec": round(elapsed, 1),
            "hard_fail": True,
            "error": f"{type(error).__name__}: {error}",
            "xlsx_path": str(xlsx_path) if xlsx_path.exists() else "",
        }
        metrics_path.write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)
        return 1

    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
