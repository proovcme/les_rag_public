"""Isolated Core ML embedding worker for mlx_host.py.

The worker speaks newline-delimited JSON over stdio:

Request:  {"id": "1", "texts": ["..."]}
Response: {"id": "1", "vectors": [[...]], "dim": 1024, "sec": 0.123}

It deliberately keeps Core ML runtime state outside the main FastAPI process.
If Core ML hits a native SIGSEGV, launchd only has to recover this child.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any


os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


class CoreMLEmbeddingWorker:
    def __init__(
        self,
        *,
        model_id: str,
        model_path: str,
        seq_len: int,
        batch_size: int,
        compute_units: str,
        local_files_only: bool,
    ):
        self.model_id = model_id
        self.model_path = model_path
        self.seq_len = seq_len
        self.batch_size = max(1, batch_size)
        self.compute_units = compute_units
        self.local_files_only = local_files_only
        self._model = None
        self._tokenizer = None

    def _compute_unit(self):
        import coremltools as ct

        units = {
            "all": ct.ComputeUnit.ALL,
            "cpu_only": ct.ComputeUnit.CPU_ONLY,
            "cpu_and_gpu": ct.ComputeUnit.CPU_AND_GPU,
            "cpu_and_ne": ct.ComputeUnit.CPU_AND_NE,
        }
        if self.compute_units not in units:
            raise ValueError(f"unknown compute units: {self.compute_units!r}")
        return units[self.compute_units]

    def load(self):
        if self._model is not None and self._tokenizer is not None:
            return
        with redirect_stdout(sys.stderr):
            import coremltools as ct
            from transformers import AutoTokenizer

            model_path = Path(self.model_path).expanduser()
            if not model_path.exists():
                raise FileNotFoundError(f"Core ML embedding package not found: {model_path}")
            print(
                f"[coreml-embed-worker] loading {model_path} "
                f"seq_len={self.seq_len} batch={self.batch_size} units={self.compute_units}",
                file=sys.stderr,
                flush=True,
            )
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_id,
                local_files_only=self.local_files_only,
            )
            self._model = ct.models.MLModel(str(model_path), compute_units=self._compute_unit())
            print("[coreml-embed-worker] ready", file=sys.stderr, flush=True)

    @staticmethod
    def _normalize(vecs: Any):
        import numpy as np

        vecs = np.asarray(vecs, dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.maximum(norms, 1e-12)

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with redirect_stdout(sys.stderr):
            import numpy as np

            self.load()
            assert self._model is not None
            assert self._tokenizer is not None

            vectors: list[Any] = []
            for start in range(0, len(texts), self.batch_size):
                batch = list(texts[start : start + self.batch_size])
                real_size = len(batch)
                if real_size < self.batch_size:
                    batch.extend([batch[-1]] * (self.batch_size - real_size))
                tokens = self._tokenizer(
                    batch,
                    padding="max_length",
                    truncation=True,
                    max_length=self.seq_len,
                    return_tensors="np",
                )
                out = self._model.predict(
                    {
                        "input_ids": tokens["input_ids"].astype(np.int32),
                        "attention_mask": tokens["attention_mask"].astype(np.int32),
                    }
                )["embeddings"]
                vectors.append(self._normalize(out)[:real_size])
            return [v.tolist() for v in np.concatenate(vectors, axis=0)]


def serve(args: argparse.Namespace) -> int:
    worker = CoreMLEmbeddingWorker(
        model_id=args.model_id,
        model_path=args.model_path,
        seq_len=args.seq_len,
        batch_size=args.batch_size,
        compute_units=args.compute_units,
        local_files_only=args.local_files_only,
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
            texts = request.get("texts")
            if not isinstance(texts, list):
                raise ValueError("request.texts must be a list")
            started = time.perf_counter()
            vectors = worker.encode([str(text) for text in texts])
            sec = time.perf_counter() - started
            dim = len(vectors[0]) if vectors else 0
            response = {"id": request_id, "vectors": vectors, "dim": dim, "sec": sec}
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            response = {"id": request_id, "error": str(exc)}
        out.write(json.dumps(response, ensure_ascii=False) + "\n")
        out.flush()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated Core ML embedding JSONL worker.")
    parser.add_argument("--model-id", default="Qwen/Qwen3-Embedding-0.6B")
    parser.add_argument("--model-path", default="artifacts/coreml/qwen3_embedding_06b_b1_s1024_static.mlpackage")
    parser.add_argument("--seq-len", type=int, default=1024)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--compute-units", choices=["all", "cpu_only", "cpu_and_gpu", "cpu_and_ne"], default="cpu_only")
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()
    return serve(args)


if __name__ == "__main__":
    raise SystemExit(main())
