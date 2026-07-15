#!/usr/bin/env python3
"""Run one real VOR through the configured smeta model and require a usable XLSX."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model", default="gemma4:12b")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--workflow-file", type=Path)
    parser.add_argument("--max-tokens", type=int, default=5000)
    parser.add_argument("--only-row", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"source not found: {args.source}")
    if args.env_file:
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=True)
    os.environ["LES_LLM_PROVIDER"] = "ollama"
    os.environ["OLLAMA_MODEL"] = args.model
    os.environ["LES_SMETA_DOCUMENT_PROVIDER"] = "ollama"
    os.environ["LES_SMETA_DOCUMENT_MODEL"] = args.model
    os.environ["LES_SMETA_DOCUMENT_FALLBACK_MODEL"] = "off"
    os.environ["LES_SMETA_DOCUMENT_MAX_TOKENS"] = str(max(900, args.max_tokens))

    from proxy.services.smeta_chat_adapter_service import _smeta_document_exchange
    if args.workflow_file:
        spec = importlib.util.spec_from_file_location("les_candidate_document_workflow", args.workflow_file)
        if spec is None or spec.loader is None:
            raise SystemExit(f"cannot load workflow: {args.workflow_file}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        run_vor_document_workflow = module.run_vor_document_workflow
    else:
        from proxy.smeta_core import document_workflow as module

        run_vor_document_workflow = module.run_vor_document_workflow

    events: list[dict] = []
    def progress(event: dict) -> None:
        events.append(dict(event))
        print(json.dumps({"progress": event}, ensure_ascii=False), flush=True)

    def exchange(messages: list[dict], tools: list[dict]) -> dict:
        verbose = args.verbose or bool(args.only_row)
        if verbose and messages and messages[-1].get("role") == "tool":
            print(json.dumps({
                "last_tool_result": {
                    "name": messages[-1].get("name"),
                    "content": str(messages[-1].get("content") or "")[:6000],
                }
            }, ensure_ascii=False), flush=True)
        response = _smeta_document_exchange(messages, tools)
        if verbose:
            print(json.dumps({
                "model_turn": {
                    "tool_calls": [{
                        "name": str((call.get("function") or {}).get("name") or ""),
                        "arguments": str((call.get("function") or {}).get("arguments") or "")[:4000],
                    }
                        for call in (response.get("tool_calls") or [])
                        if isinstance(call, dict)
                    ],
                    "content": str(response.get("content") or "")[:300],
                    "model": response.get("_les_model"),
                    "fallback_from": response.get("_les_fallback_from"),
                }
            }, ensure_ascii=False), flush=True)
        return response

    if args.only_row:
        intake = module.intake_vor_document(args.source) if args.workflow_file else __import__(
            "proxy.smeta_core.source_intake", fromlist=["intake_vor_document"]
        ).intake_vor_document(args.source)
        all_rows = [dict(item) for item in (intake.get("work_items") or [])]
        index = args.only_row - 1
        if index < 0 or index >= len(all_rows):
            raise SystemExit(f"row is outside 1..{len(all_rows)}")
        result = module._run_batch_norm_agent(
            [all_rows[index]],
            exchange,
            candidate_limit=8,
            progress=progress,
            user_request="Собери первую ЛСР по приложенной ВОР",
            context_rows=all_rows,
        )
        selections = dict(result.get("selections") or {})
        print(json.dumps({
            "diagnostic_ok": True,
            "row": args.only_row,
            "selections": selections,
            "turns": (result.get("agent_trace") or {}).get("turns"),
        }, ensure_ascii=False, default=str))
        return 0

    result = run_vor_document_workflow(
        args.source,
        exchange=exchange,
        out_xlsx=args.output,
        out_report=args.report,
        source_name=args.source.name,
        user_request="Собери первую ЛСР по приложенной ВОР",
        batch_size=args.batch_size,
        progress=progress,
    )
    output = Path(result.get("xlsx_path") or "")
    selections = list(result.get("selections") or [])
    model_trace = list(result.get("model_trace") or [])
    models = sorted({
        str(item.get("model") or item.get("_les_model") or "")
        for item in model_trace
        if isinstance(item, dict) and (item.get("model") or item.get("_les_model"))
    })
    summary = {
        "ok": output.is_file() and output.stat().st_size > 0 and bool(selections),
        "source": str(args.source),
        "xlsx": str(output),
        "xlsx_bytes": output.stat().st_size if output.is_file() else 0,
        "rows": len(result.get("intake", {}).get("work_items") or []),
        "selections": len(selections),
        "models": models or [args.model],
        "fallback_disabled": True,
        "last_event": events[-1] if events else {},
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
