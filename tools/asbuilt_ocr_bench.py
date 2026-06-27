#!/usr/bin/env python3
"""asbuilt_ocr_bench.py — «модель решают тесты»: бенч vision-OCR на эталонных листах.

Гоняет конвейер приёмки (`asbuilt_intake_service.extract_rows`) по листам с известным
ground-truth и считает точность (recall по числовым якорям, мультимножеством — учитывает
повторы вроде двух «1003») + латентность. Любой движок/модель сравнивается одинаково —
так выбираем модель не на глаз, а по цифрам.

Эталон — ручной разбор 4 листов АУПС/СОУЭ L5 (МФК «Лахта центр», комплект 13.06.2023).

Примеры:
  uv run python tools/asbuilt_ocr_bench.py --dir "/path/АУПС-СОУЭ" --engine cloud --model gpt-4.1
  uv run python tools/asbuilt_ocr_bench.py --dir "..." --engine local --model qwen3-vl:8b
  uv run python tools/asbuilt_ocr_bench.py --dir "..." --models cloud:gpt-4.1 local:gemma4:12b local:qwen3-vl:8b
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proxy.services.asbuilt_intake_service import extract_rows  # noqa: E402
from proxy.services.asbuilt_ocr import resolve_engine  # noqa: E402

# Ground-truth: для каждого листа — мультимножество числовых якорей (кол-во из таблиц
# «смонтированного оборудования» + «ведомости»). Сопоставление по значению, имена шумят.
GROUND_TRUTH = {
    "ОП": [1003, 1003, 14, 85, 85, 4, 4, 4, 8, 4, 3, 6],
    "ПП": [1220, 1220, 89, 89, 8, 1, 2, 1, 2, 1, 1, 2],
    "РО": [491, 491, 502.5, 502.5, 8],
    "СО": [67, 67, 440, 440],
}


def _sheet_key(name: str) -> str | None:
    up = name.upper()
    for k in ("ОП", "ПП", "РО", "СО"):
        # «_ОП_», «_ПП_» … в имени листа
        if f"_{k}_" in up.replace(" ", "") or f" {k} " in up or f"_{k}" in up:
            return k
    return None


def _score(expected: list[float], got_qty: list[float]) -> tuple[int, int, int]:
    exp, gc = Counter(expected), Counter(got_qty)
    matched = sum(min(exp[v], gc[v]) for v in exp)
    spurious = sum(gc.values()) - sum(min(exp[v], gc[v]) for v in (exp.keys() & gc.keys()))
    return matched, len(expected), max(0, spurious)


def run_model(spec: str, pdfs: list[Path], rotate: str) -> dict:
    engine, _, model = spec.partition(":")
    eng = resolve_engine(engine, model=model or None)
    tot_m = tot_e = tot_s = 0
    t0 = time.time()
    per = []
    for pdf in pdfs:
        k = _sheet_key(pdf.stem)
        if k is None or k not in GROUND_TRUTH:
            continue
        st = time.time()
        res = extract_rows(pdf, rotate=rotate, ocr_engine=eng)
        dt = time.time() - st
        qty = [r.qty for r in res.kept if r.qty is not None]
        m, e, s = _score(GROUND_TRUTH[k], qty)
        tot_m += m; tot_e += e; tot_s += s
        per.append((k, m, e, s, round(dt, 1), res.error[:30]))
    return {
        "spec": spec, "engine": eng.name, "model": eng.model,
        "matched": tot_m, "expected": tot_e, "spurious": tot_s,
        "recall": (tot_m / tot_e) if tot_e else 0.0,
        "secs": round(time.time() - t0, 1), "per": per,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Бенч vision-OCR приёмки ИД на эталонных листах")
    ap.add_argument("--dir", required=True, help="папка с 4 эталонными листами АУПС/СОУЭ")
    ap.add_argument("--engine", default="", help="local|cloud (если без --models)")
    ap.add_argument("--model", default="", help="модель (если без --models)")
    ap.add_argument("--models", nargs="*", default=[], help="список спеков engine:model для сравнения")
    ap.add_argument("--rotate", default="auto")
    args = ap.parse_args()

    pdfs = sorted(p for p in Path(args.dir).glob("*.pdf"))
    if not pdfs:
        print("Нет PDF в", args.dir); return 1
    specs = args.models or [f"{args.engine or 'local'}:{args.model}".rstrip(":")]

    print(f"Листов: {len(pdfs)} | якорей всего: {sum(len(v) for v in GROUND_TRUTH.values())}\n")
    results = []
    for spec in specs:
        print(f"▶ {spec} …", flush=True)
        r = run_model(spec, pdfs, args.rotate)
        results.append(r)
        for k, m, e, s, dt, err in r["per"]:
            print(f"    {k}: {m}/{e} якорей, лишних {s}, {dt}с {('· '+err) if err else ''}")
        print(f"  Σ recall {r['recall']*100:.0f}% ({r['matched']}/{r['expected']}), "
              f"лишних {r['spurious']}, {r['secs']}с\n")

    if len(results) > 1:
        print("── РЕЙТИНГ (recall ↓, затем время ↑) ──")
        print(f"{'движок:модель':<28}{'recall':>8}{'лишних':>8}{'сек':>8}")
        for r in sorted(results, key=lambda x: (-x["recall"], x["secs"])):
            print(f"{r['spec'][:27]:<28}{r['recall']*100:>7.0f}%{r['spurious']:>8}{r['secs']:>8.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
