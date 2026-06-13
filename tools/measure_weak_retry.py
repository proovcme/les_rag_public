"""W2.7 — замер доли weak-ретраев, закрываемой словарём (на golden). [live]

ADR-11 go/no-go: словарная ступень (`expand_query_synonyms` + `expanded_quality_query`)
расширяет запрос на weak-ретрае БЕЗ LLM. Этот замер отвечает, нужна ли вообще
LLM-ступень (2-3 перефраза + RRF): если словарь закрывает большинство weak —
не нужна (ADR-11: LLM последним).

Метод: каждый golden-вопрос гоняется через `/api/retrieve-debug` (тот же путь, что
чат: гибрид→словарный ретрай→реранк). Из `retrieval_trace` берём финальный
`quality.status` и `retry_count`:

* ``strong``         — не weak, ретрай не понадобился (retry_count == 0);
* ``closed_by_dict`` — был weak, словарный ретрай поднял качество (retry_count > 0, не weak);
* ``residual_weak``  — остался weak после словаря (кандидат на LLM-ступень).

Запуск на живом рантайме (после реиндекса):
  uv run python tools/measure_weak_retry.py --cases golden/domain_fire_hvac_set.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Переиспользуем клиент и лоадер golden из rag_golden_set (тот же контракт/авторизация).
# Двойной режим: как пакет (тест, `from tools...`) и как скрипт (sys.path[0]==tools/).
try:
    from tools.rag_golden_set import GoldenClient, load_cases, local_active_key
except ImportError:  # запуск напрямую `python tools/measure_weak_retry.py`
    from rag_golden_set import GoldenClient, load_cases, local_active_key  # type: ignore

DEFAULT_CASES = Path("golden/domain_fire_hvac_set.json")

# Доля residual_weak среди всех weak, выше которой словарь «не справляется» и
# LLM-ступень оправдана. Ниже — словаря достаточно (ADR-11: LLM не тащим).
LLM_STEP_THRESHOLD = 0.34


def classify_weak_case(status: str, retry_count: int) -> str:
    """Классификация исхода ретрива по финальному качеству и факту ретрая.

    Pure-функция — единственная логика замера, покрыта офлайн-тестом.
    """
    if str(status).strip().lower() == "weak":
        return "residual_weak"
    if int(retry_count or 0) > 0:
        return "closed_by_dict"
    return "strong"


def _extract(trace: dict) -> tuple[str, int]:
    quality = trace.get("quality") or {}
    status = str(quality.get("status") or trace.get("quality_status") or "")
    retry_count = int(trace.get("retry_count") or 0)
    return status, retry_count


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="W2.7: замер доли weak, закрываемой словарём.")
    p.add_argument("--proxy-url", default=os.getenv("LES_PROXY_URL", "http://127.0.0.1:8050"))
    p.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    p.add_argument("--api-key", default=os.getenv("LES_USER_KEY", os.getenv("LES_ADMIN_KEY", "")))
    p.add_argument("--key-db", default="", help="Прочитать активный ключ из локальной SQLite БД")
    p.add_argument("--key-role", default="", choices=("", "user", "admin"))
    p.add_argument("--timeout", type=float, default=float(os.getenv("LES_GOLDEN_TIMEOUT", "30")))
    p.add_argument("--json", action="store_true", help="Машиночитаемый JSON-итог.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.proxy_url = args.proxy_url.rstrip("/")
    api_key = args.api_key or (local_active_key(args.key_db, args.key_role) if args.key_db else "")

    try:
        cases = load_cases(args.cases)
    except Exception as exc:
        print(f"Не загрузить golden {args.cases}: {exc}", file=sys.stderr)
        return 2

    client = GoldenClient(args.proxy_url, args.timeout, api_key)
    buckets = {"strong": 0, "closed_by_dict": 0, "residual_weak": 0}
    residual_ids: list[str] = []
    rows: list[dict] = []

    for case in cases:
        payload = {"question": case.question, "top_k": case.top_k}
        if case.dataset_filter:
            payload["dataset_filter"] = case.dataset_filter
        res = client.post_json("/api/rag/retrieve-debug", payload)
        if res.status != 200:
            print(f"[ERR ] {case.id:28} HTTP {res.status} {res.body[:120]}", file=sys.stderr)
            return 1
        trace = res.json().get("retrieval_trace") or {}
        status, retry_count = _extract(trace)
        bucket = classify_weak_case(status, retry_count)
        buckets[bucket] += 1
        if bucket == "residual_weak":
            residual_ids.append(case.id)
        rows.append({"id": case.id, "status": status, "retry_count": retry_count, "bucket": bucket})
        if not args.json:
            print(f"[{bucket:14}] {case.id:28} status={status or '-':6} retry={retry_count}")

    total = max(1, sum(buckets.values()))
    total_weak = buckets["closed_by_dict"] + buckets["residual_weak"]
    closed_share = buckets["closed_by_dict"] / total_weak if total_weak else 0.0
    residual_share = buckets["residual_weak"] / total_weak if total_weak else 0.0
    llm_recommended = bool(total_weak) and residual_share > LLM_STEP_THRESHOLD

    summary = {
        "cases": total,
        "strong": buckets["strong"],
        "weak_total": total_weak,
        "closed_by_dict": buckets["closed_by_dict"],
        "residual_weak": buckets["residual_weak"],
        "closed_share": round(closed_share, 3),
        "residual_share": round(residual_share, 3),
        "residual_ids": residual_ids,
        "llm_step_recommended": llm_recommended,
        "threshold": LLM_STEP_THRESHOLD,
    }
    if args.json:
        print(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2))
        return 0

    print("\n── W2.7 итог ──")
    print(f"кейсов: {total} · strong: {buckets['strong']} · weak: {total_weak}")
    if total_weak:
        print(f"словарь закрыл: {buckets['closed_by_dict']}/{total_weak} ({closed_share:.0%})")
        print(f"осталось weak: {buckets['residual_weak']}/{total_weak} ({residual_share:.0%})")
        if residual_ids:
            print(f"residual: {', '.join(residual_ids)}")
        verdict = (
            "LLM-ступень ОПРАВДАНА (residual выше порога)"
            if llm_recommended
            else f"словаря достаточно — LLM-ступень НЕ нужна (residual ≤ {LLM_STEP_THRESHOLD:.0%}, ADR-11)"
        )
        print(f"вердикт: {verdict}")
    else:
        print("weak-ретраев на наборе нет — словарь/гибрид справляются, LLM-ступень не нужна.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
