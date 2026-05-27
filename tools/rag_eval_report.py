#!/usr/bin/env python3
"""Summarize LES RAG baseline JSONL/human logs.

The report is intentionally dependency-free. It gives us a stable scoreboard
now, while keeping the emitted JSONL shape close enough to feed optional Ragas
experiments later when golden cases include reference answers and contexts.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


HUMAN_LINE_RE = re.compile(
    r"^\[(?P<mark>[A-Z ]+)\]\s+"
    r"(?P<mode>\w+)\s+"
    r"(?P<case_id>\S+)\s+"
    r"(?P<elapsed>\d+(?:\.\d+)?)s\s+"
    r"(?P<detail>.*)$"
)


@dataclass(frozen=True)
class EvalRecord:
    case_id: str
    mode: str
    ok: bool
    detail: str
    elapsed: float
    guarded_stop: bool = False
    crag_status: str = ""
    question: str = ""
    answer: str = ""
    reference_answer: str = ""
    expected_terms: tuple[str, ...] = ()
    source_hints: tuple[str, ...] = ()


@dataclass
class EvalSummary:
    total: int = 0
    ok: int = 0
    failed: int = 0
    guarded: int = 0
    ragas_ready: int = 0
    by_mode: dict[str, int] = field(default_factory=dict)
    crag: dict[str, int] = field(default_factory=dict)
    avg_elapsed: float = 0.0
    p95_elapsed: float = 0.0
    slowest: list[dict[str, Any]] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.ok / self.total if self.total else 0.0


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value if str(item))
    return ()


def record_from_json(raw: dict[str, Any]) -> EvalRecord:
    return EvalRecord(
        case_id=str(raw.get("case_id") or raw.get("id") or ""),
        mode=str(raw.get("mode") or ""),
        ok=bool(raw.get("ok")),
        detail=str(raw.get("detail") or ""),
        elapsed=float(raw.get("elapsed") or 0.0),
        guarded_stop=bool(raw.get("guarded_stop")),
        crag_status=str(raw.get("crag_status") or ""),
        question=str(raw.get("question") or ""),
        answer=str(raw.get("answer") or ""),
        reference_answer=str(raw.get("reference_answer") or ""),
        expected_terms=_tuple_of_strings(raw.get("expected_terms")),
        source_hints=_tuple_of_strings(raw.get("source_hints")),
    )


def record_from_human_line(line: str) -> EvalRecord | None:
    match = HUMAN_LINE_RE.match(line.strip())
    if not match:
        return None
    mark = match.group("mark").strip()
    detail = (match.group("detail") or "").strip()
    crag_match = re.search(r"\bcrag=(\w+)", detail)
    return EvalRecord(
        case_id=match.group("case_id"),
        mode=match.group("mode"),
        ok=mark in {"OK", "GUARD"},
        detail=detail,
        elapsed=float(match.group("elapsed")),
        guarded_stop=mark == "GUARD",
        crag_status=crag_match.group(1) if crag_match else "",
    )


def load_records(paths: list[Path]) -> list[EvalRecord]:
    records: list[EvalRecord] = []
    for path in paths:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("{"):
                try:
                    records.append(record_from_json(json.loads(stripped)))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
                continue
            parsed = record_from_human_line(stripped)
            if parsed is not None:
                records.append(parsed)
    return records


def summarize(records: list[EvalRecord]) -> EvalSummary:
    summary = EvalSummary(total=len(records))
    elapsed = [record.elapsed for record in records if record.elapsed > 0]
    for record in records:
        summary.ok += 1 if record.ok else 0
        summary.failed += 0 if record.ok else 1
        summary.guarded += 1 if record.guarded_stop else 0
        summary.ragas_ready += 1 if record.question and record.answer and record.reference_answer else 0
        summary.by_mode[record.mode] = summary.by_mode.get(record.mode, 0) + 1
        if record.crag_status:
            summary.crag[record.crag_status] = summary.crag.get(record.crag_status, 0) + 1
    if elapsed:
        summary.avg_elapsed = round(statistics.fmean(elapsed), 3)
        if len(elapsed) == 1:
            summary.p95_elapsed = round(elapsed[0], 3)
        else:
            summary.p95_elapsed = round(statistics.quantiles(elapsed, n=20, method="inclusive")[18], 3)
    summary.slowest = [
        {
            "case_id": record.case_id,
            "mode": record.mode,
            "elapsed": round(record.elapsed, 3),
            "ok": record.ok,
            "guarded_stop": record.guarded_stop,
        }
        for record in sorted(records, key=lambda item: item.elapsed, reverse=True)[:5]
    ]
    return summary


def summary_payload(summary: EvalSummary) -> dict[str, Any]:
    return {
        "total": summary.total,
        "ok": summary.ok,
        "failed": summary.failed,
        "guarded": summary.guarded,
        "pass_rate": round(summary.pass_rate, 4),
        "ragas_ready": summary.ragas_ready,
        "by_mode": summary.by_mode,
        "crag": summary.crag,
        "latency": {
            "avg_elapsed": summary.avg_elapsed,
            "p95_elapsed": summary.p95_elapsed,
            "slowest": summary.slowest,
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize LES RAG baseline logs.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable summary.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    records = load_records(args.paths)
    summary = summarize(records)
    payload = summary_payload(summary)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "RAG eval report: "
            f"total={summary.total} ok={summary.ok} failed={summary.failed} "
            f"guarded={summary.guarded} pass_rate={summary.pass_rate:.1%} "
            f"avg={summary.avg_elapsed:.2f}s p95={summary.p95_elapsed:.2f}s "
            f"ragas_ready={summary.ragas_ready}"
        )
        if summary.crag:
            print("CRAG: " + ", ".join(f"{key}={value}" for key, value in sorted(summary.crag.items())))
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
