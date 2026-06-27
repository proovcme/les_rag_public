#!/usr/bin/env python3
"""router_bench.py — бенч tool-selection точности агент-роутера (Ярус 2).

Гоняет `agent_router_service._classify` на golden-наборе (вопрос → ожидаемый инструмент) и
считает **tool-selection accuracy**: overall, по каждому инструменту, и ОТДЕЛЬНО на
переформулировках (главный тест устойчивости к «шагу в сторону»). Печатает промахи
(вопрос → что выбрала модель вместо ожидаемого) — кандидаты под router-LoRA.

Нужен живой малый LLM (OpenAI-совместимый: env OPENAI_BASE_URL + OPENAI_API_KEY [+ OPENAI_MODEL]).
Если модели нет — бенч это явно сообщает и НЕ падает молча. Для проверки самого каркаса без LLM:
`--self-test` (мокает _classify эталоном — каркас обязан дать 100%).

Запуск (живой прогон):
    OPENAI_BASE_URL=… OPENAI_API_KEY=… OPENAI_MODEL=… \
        uv run python tools/router_bench.py --cases golden/router_eval_set.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# чтобы импортировать proxy.* при запуске из корня репо
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_CASES = Path("golden/router_eval_set.json")


@dataclass
class Case:
    id: str
    question: str
    expected: str
    rephrase: bool


@dataclass
class Outcome:
    case: Case
    predicted: str

    @property
    def ok(self) -> bool:
        return self.predicted == self.case.expected


def load_cases(path: Path) -> list[Case]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[Case] = []
    for c in data.get("cases", []):
        out.append(Case(id=c["id"], question=c["question"],
                        expected=c["expected"], rephrase=bool(c.get("rephrase", False))))
    return out


def _live_classifier() -> Callable[[str], str]:
    from proxy.services import agent_router_service as ar
    return ar._classify  # noqa: SLF001 — это и есть точка под замер


def _self_test_classifier(cases: list[Case]) -> Callable[[str], str]:
    """Эталонный «мок»: возвращает ожидаемый инструмент по вопросу. Проверяет КАРКАС бенча
    (загрузка/учёт/отчёт), не модель — обязан дать accuracy=1.0."""
    truth = {c.question: c.expected for c in cases}
    return lambda q: truth.get(q, "none")


def run(cases: list[Case], classify: Callable[[str], str]) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for c in cases:
        try:
            pred = classify(c.question)
        except Exception as err:  # noqa: BLE001
            pred = f"<error:{type(err).__name__}>"
        outcomes.append(Outcome(case=c, predicted=pred))
    return outcomes


def _acc(items: list[Outcome]) -> tuple[int, int, float]:
    n = len(items)
    hits = sum(1 for o in items if o.ok)
    return hits, n, (hits / n if n else 0.0)


def report(outcomes: list[Outcome]) -> dict[str, Any]:
    hits, n, overall = _acc(outcomes)
    reph = [o for o in outcomes if o.case.rephrase]
    base = [o for o in outcomes if not o.case.rephrase]
    rh, rn, racc = _acc(reph)
    bh, bn, bacc = _acc(base)

    by_tool: dict[str, list[Outcome]] = defaultdict(list)
    for o in outcomes:
        by_tool[o.case.expected].append(o)

    print("=" * 64)
    print("ROUTER BENCH — tool-selection accuracy")
    print("=" * 64)
    print(f"OVERALL:        {hits}/{n}  = {overall:.1%}")
    print(f"  base (канон): {bh}/{bn}  = {bacc:.1%}")
    print(f"  ПЕРЕФОРМУЛ.:  {rh}/{rn}  = {racc:.1%}   ← главный тест устойчивости")
    print("-" * 64)
    print("По инструментам:")
    tool_acc: dict[str, float] = {}
    for tool in sorted(by_tool):
        th, tn, tacc = _acc(by_tool[tool])
        tool_acc[tool] = tacc
        flag = "  ⚠ КАНДИДАТ-LoRA" if tacc < 0.67 and tn >= 2 else ""
        print(f"  {tool:18s} {th}/{tn} = {tacc:.0%}{flag}")
    misses = [o for o in outcomes if not o.ok]
    if misses:
        print("-" * 64)
        print(f"ПРОМАХИ ({len(misses)}):")
        for o in misses:
            tag = " [rephrase]" if o.case.rephrase else ""
            print(f"  [{o.case.id}]{tag} ждали «{o.case.expected}» → выбрала «{o.predicted}»")
            print(f"      «{o.case.question}»")
    print("=" * 64)

    return {
        "overall": overall, "overall_hits": hits, "overall_n": n,
        "base_acc": bacc, "rephrase_acc": racc,
        "by_tool": tool_acc,
        "misses": [{"id": o.case.id, "expected": o.case.expected,
                    "predicted": o.predicted, "question": o.case.question,
                    "rephrase": o.case.rephrase} for o in misses],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Router tool-selection bench")
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    ap.add_argument("--self-test", action="store_true",
                    help="мок-эталон вместо LLM (проверка каркаса, должно быть 100%)")
    ap.add_argument("--json", type=Path, default=None, help="записать сводку JSON")
    args = ap.parse_args(argv)

    if not args.cases.exists():
        print(f"нет golden-набора: {args.cases}", file=sys.stderr)
        return 2
    cases = load_cases(args.cases)
    if not cases:
        print("golden-набор пуст", file=sys.stderr)
        return 2

    if args.self_test:
        classify = _self_test_classifier(cases)
    else:
        if not (os.getenv("OPENAI_BASE_URL") and os.getenv("OPENAI_API_KEY")):
            print("LLM недоступен: задайте OPENAI_BASE_URL и OPENAI_API_KEY (+OPENAI_MODEL) "
                  "для живого прогона, или --self-test для проверки каркаса.", file=sys.stderr)
            return 3
        classify = _live_classifier()

    outcomes = run(cases, classify)
    summary = report(outcomes)
    if args.json:
        args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON → {args.json}")
    # self-test обязан быть идеальным; живой прогон — информативный (всегда rc=0)
    if args.self_test and summary["overall"] < 1.0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
