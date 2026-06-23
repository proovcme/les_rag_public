"""CLI harvest-петли: verify-правки → train-set + таксономия ошибок.

    uv run python tools/harvest_dataset.py            # собрать + показать сводку
    uv run python tools/harvest_dataset.py --out data/train --json

Train-set (картинка→target) — базонезависимый актив для бенча/LoRA. Таксономия
показывает, systematic ли ошибки распознавания (есть ли смысл в LoRA).
"""
from __future__ import annotations

import argparse
import json

from proxy.services.harvest_service import build_training_set, error_taxonomy


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Harvest verify → train-set + error taxonomy")
    ap.add_argument("--out", default="data/train")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    manifest = build_training_set(args.out)
    tax = error_taxonomy()

    if args.json:
        print(json.dumps({"manifest": manifest, "taxonomy": tax}, ensure_ascii=False, indent=2))
        return 0

    print(f"train-set: {manifest['samples']} образцов → {manifest['dataset']}")
    print(f"  по вердиктам: {manifest['by_verdict']}")
    print(f"  с картинкой: {manifest['with_image']} · с предсказанием (для диффа): {manifest['with_pred_rows']}")
    print(f"\nтаксономия ошибок: corrected={tax['corrected_records']} "
          f"проанализировано={tax['analyzed']} без_pred={tax['skipped_no_pred']}")
    for cls, n in tax["by_class"].items():
        print(f"  {cls:16} {n}")
    if tax["dominant"]:
        d = tax["dominant"]
        print(f"  доминирует: {d['class']} ({d['share']:.0%})")
    print(f"  LoRA-сигнал: {'ДА' if tax['lora_signal'] else 'нет (копим/добиваем промптом)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
