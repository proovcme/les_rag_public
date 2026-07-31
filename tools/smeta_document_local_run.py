"""Run the canonical document-to-LSR workflow locally with resumable checkpoints.

The runner is diagnostic transport only. It does not choose norms, resources,
prices, coverage, or professional conclusions; the configured model owns those
decisions through the same workflow and tools used by chat.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from proxy.services import smeta_chat_adapter_service as adapters
from proxy.services.smeta_chat_application_service import (
    _load_document_checkpoint,
    _source_fingerprint,
    _write_document_checkpoint,
)
from proxy.smeta_core.document_workflow import run_vor_document_workflow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="ВОР/спецификация: PDF, XLSX или XLSM")
    parser.add_argument(
        "--request",
        default="Составь сметный расчёт по этой ведомости",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("storage/local_runs"))
    parser.add_argument("--candidate-limit", type=int, default=8)
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Строк в независимом модельном пакете; 1 безопасен для локального Qwen",
    )
    parser.add_argument("--book", default="")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Не читать существующий checkpoint; сохранение новых checkpoint остаётся включено",
    )
    args = parser.parse_args(argv)

    source = args.source.resolve()
    if not source.exists():
        parser.error(f"нет файла: {source}")
    if source.suffix.lower() not in {".pdf", ".xlsx", ".xlsm"}:
        parser.error("поддерживаются только PDF, XLSX и XLSM")

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _source_fingerprint(source)
    checkpoint_path = (
        out_dir / ".checkpoints" / f"{fingerprint['sha256']}.json"
    )
    resume_result = None
    if not args.fresh:
        resume_result = _load_document_checkpoint(
            checkpoint_path,
            source_fingerprint=fingerprint,
        )

    started = time.monotonic()

    def progress(event: dict[str, Any]) -> None:
        elapsed = time.monotonic() - started
        detail = {
            key: value
            for key, value in event.items()
            if key != "phase" and not isinstance(value, (dict, list))
        }
        print(
            f"[{elapsed:7.1f}s] {str(event.get('phase') or '?'):<24} "
            f"{json.dumps(detail, ensure_ascii=False)[:180]}",
            flush=True,
        )

    def checkpoint(agent_result: dict[str, Any]) -> None:
        _write_document_checkpoint(
            checkpoint_path,
            source_fingerprint=fingerprint,
            agent_result=agent_result,
        )

    stem = source.stem.replace(" ", "_")
    print(f"source      : {source}")
    print(f"provider    : {os.getenv('LES_SMETA_DOCUMENT_PROVIDER', 'runtime default')}")
    print(f"batch       : {args.batch_size}")
    print(f"checkpoint  : {checkpoint_path}")
    if resume_result:
        print(
            "resume      : "
            f"{len(resume_result.get('selections') or {})} completed rows"
        )
    print("-" * 96, flush=True)

    try:
        workflow = run_vor_document_workflow(
            source,
            exchange=adapters._smeta_document_exchange,
            mapping_exchange=adapters._smeta_document_mapping_exchange,
            candidate_limit=args.candidate_limit,
            book=args.book or None,
            out_xlsx=out_dir / f"{stem}.lsr.xlsx",
            out_report=out_dir / f"{stem}.report.json",
            progress=progress,
            source_name=source.name,
            user_request=args.request,
            batch_size=args.batch_size,
            max_agent_turns=args.max_turns,
            resume_agent_result=resume_result,
            batch_checkpoint=checkpoint,
            require_scoped_search=True,
        )
    except KeyboardInterrupt:
        print(f"\nОстановлено. Продолжение использует checkpoint: {checkpoint_path}")
        return 130
    except Exception as error:
        print(f"\nFAILED: {type(error).__name__}: {error}")
        if checkpoint_path.exists():
            print(f"Повторный запуск продолжит с: {checkpoint_path}")
        return 1

    summary = (workflow.get("lsr") or {}).get("summary") or {}
    checkpoint_path.unlink(missing_ok=True)
    print("-" * 96)
    print(json.dumps({
        "result_status": summary.get("result_status"),
        "input_rows": summary.get("input_rows"),
        "bound_rows": summary.get("bound_rows"),
        "open_rows": summary.get("open_rows"),
        "total": summary.get("total"),
        "elapsed_sec": round(time.monotonic() - started, 1),
    }, ensure_ascii=False, indent=2))
    print(f"xlsx   : {workflow.get('xlsx_path')}")
    print(f"report : {workflow.get('report_path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
