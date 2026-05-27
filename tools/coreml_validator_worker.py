"""Isolated Core ML validator worker for mlx_host.py."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _labels(raw: str) -> list[str]:
    return [label.strip() for label in raw.split(",") if label.strip()]


def serve(args: argparse.Namespace) -> int:
    os.environ["COREML_VALIDATOR_LOCAL_FILES_ONLY"] = "true" if args.local_files_only else "false"
    with redirect_stdout(sys.stderr):
        from mlx_host import CoreMLValidator, ValidateRequest

        validator = CoreMLValidator(
            model_path=args.model_path,
            tokenizer_id=args.tokenizer_id,
            seq_len=args.seq_len,
            attention_mask_rank=args.attention_mask_rank,
            compute_units=args.compute_units,
            labels=_labels(args.labels),
            min_confidence=args.min_confidence,
            context_mode=args.context_mode,
            pair_mode=args.pair_mode,
            entailment_threshold=args.entailment_threshold,
            contradiction_threshold=args.contradiction_threshold,
            decision_margin=args.decision_margin,
        )

    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            if request.get("cmd") == "shutdown":
                break
            req = ValidateRequest(
                question=str(request.get("question") or ""),
                answer=str(request.get("answer") or ""),
                context=str(request.get("context") or ""),
            )
            with redirect_stdout(sys.stderr):
                result = validator.validate(req)
            response = {"id": request_id, "result": result}
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            response = {"id": request_id, "error": str(exc)}
        out.write(json.dumps(response, ensure_ascii=False) + "\n")
        out.flush()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated Core ML validator JSONL worker.")
    parser.add_argument("--model-path", default="artifacts/coreml/validator_minilm_l6_b1_s512.mlpackage")
    parser.add_argument("--tokenizer-id", default="MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli")
    parser.add_argument("--seq-len", type=int, default=512)
    parser.add_argument("--attention-mask-rank", type=int, default=4)
    parser.add_argument("--compute-units", choices=["all", "cpu_only", "cpu_and_gpu", "cpu_and_ne"], default="cpu_only")
    parser.add_argument("--context-mode", choices=["full", "windows"], default="windows")
    parser.add_argument("--pair-mode", choices=["answer", "qa", "claim"], default="answer")
    parser.add_argument("--labels", default="entailment,neutral,contradiction")
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--entailment-threshold", type=float, default=0.8)
    parser.add_argument("--contradiction-threshold", type=float, default=0.6)
    parser.add_argument("--decision-margin", type=float, default=0.05)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()
    return serve(args)


if __name__ == "__main__":
    raise SystemExit(main())
