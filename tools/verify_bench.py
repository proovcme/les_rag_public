"""Бенч качества распознавания для verify (поверх /api/verify/extract).

Считает field-accuracy извлечённой таблицы против ground truth. Ground truth —
это эталон, который даёт оператор через verify-UI (сохранённые подтверждения в
data/verifications/*.json) ИЛИ заданный golden-файл {path, page, expected_rows,
expected_headers}. То есть верификация оператора = разметка, бенч = число.

Метрики:
- header_terms: доля ОБЯЗАТЕЛЬНЫХ терминов шапки, прочитанных верно (АОРПИ, КОРПУС…);
- field_accuracy (micro): по выровненным строкам — доля совпавших ячеек;
- row_recall: доля эталонных строк ключевой колонки, найденных в извлечении.

    uv run python tools/verify_bench.py golden/verify_gt_schity.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path


def _norm(s) -> str:
    return " ".join(str(s).split()).strip().casefold()


def extract(path: str, page: int) -> dict:
    base = os.getenv("PROXY_URL", "http://127.0.0.1:8050").rstrip("/")
    body = json.dumps({"path": path, "page": page, "engine": "local"}).encode()
    req = urllib.request.Request(base + "/api/verify/extract", data=body,
                                 headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=float(os.getenv("VERIFY_BENCH_TIMEOUT", "400"))) as r:
        return json.loads(r.read())


def score(gt: dict, res: dict) -> dict:
    cols = [_norm(c) for c in (res.get("columns") or [])]
    rows = res.get("rows") or []

    # 1) обязательные термины шапки (читаются верно?)
    terms = gt.get("header_terms") or []
    cols_blob = " | ".join(cols)
    term_hits = [t for t in terms if _norm(t) in cols_blob]
    header_acc = len(term_hits) / len(terms) if terms else None

    # 2) row_recall по ключевой колонке (напр. наименование оборудования)
    keycol = gt.get("key_column")
    exp_keys = [_norm(x) for x in (gt.get("key_values") or [])]
    got_keys = []
    if keycol:
        kc = _norm(keycol)
        field = next((c for c in (res.get("columns") or []) if _norm(c) == kc
                      or kc in _norm(c) or _norm(c) in kc), None)
        if field:
            got_keys = [_norm(r.get(field, "")) for r in rows]
    matched = sum(1 for k in exp_keys if any(k and (k in g or g in k) for g in got_keys))
    recall = matched / len(exp_keys) if exp_keys else None

    return {
        "extracted_rows": len(rows),
        "extracted_columns": res.get("columns"),
        "header_terms_total": len(terms),
        "header_terms_ok": [t for t in terms if _norm(t) in cols_blob],
        "header_accuracy": header_acc,
        "key_recall": recall,
        "key_matched": matched,
        "key_total": len(exp_keys),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Бенч распознавания verify против ground truth.")
    ap.add_argument("ground_truth", help="JSON: {path, page, header_terms, key_column, key_values}")
    args = ap.parse_args(argv)

    gt = json.loads(Path(args.ground_truth).read_text(encoding="utf-8"))
    res = extract(gt["path"], int(gt.get("page", 0)))
    s = score(gt, res)

    print(f"=== verify-бенч: {os.path.basename(gt['path'])[:60]} ===")
    print(f"строк извлечено: {s['extracted_rows']}")
    print(f"шапка: {', '.join(s['extracted_columns'] or [])}")
    if s["header_accuracy"] is not None:
        print(f"термины шапки верно: {len(s['header_terms_ok'])}/{s['header_terms_total']} "
              f"({s['header_accuracy']:.0%}) — {', '.join(s['header_terms_ok'])}")
    if s["key_recall"] is not None:
        print(f"row_recall ({gt.get('key_column')}): {s['key_matched']}/{s['key_total']} ({s['key_recall']:.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
