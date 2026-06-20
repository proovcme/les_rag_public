"""Field-accuracy benchmark for schema-constrained extraction.

Shared first step for two questions: "how good is local extraction with
proxy/services/structured_extract" and "do we need a LoRA". Mirrors lift's
metric — field accuracy over scored fields — so numbers are comparable.

Each case (golden/extract_eval_set.json) is {name, schema, instruction, context,
expected}. The runner pushes ``context`` through ``structured_extract.extract``
with a chosen backend, then scores the returned JSON field-by-field against
``expected``.

    # against the local MLX OpenAI endpoint:
    uv run python tools/extract_bench.py --backend mlx --model <id>
    # against a cloud OpenAI-compatible endpoint (uses native response_format):
    uv run python tools/extract_bench.py --backend cloud --base-url ... --model ... --api-key-env OPENAI_API_KEY

The ``echo`` backend returns each case's own expected JSON — it exercises the
harness end-to-end (perfect score) without a model and is what the tests use.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from proxy.services import structured_extract as se

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "golden" / "extract_eval_set.json"


@dataclass
class ExtractCase:
    name: str
    schema: dict
    instruction: str
    context: str
    expected: dict


def load_cases(path: Path = DEFAULT_CASES) -> list[ExtractCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise ValueError(f"cases must be a list or object with 'cases': {path}")
    return [
        ExtractCase(
            name=str(item["name"]),
            schema=item["schema"],
            instruction=item.get("instruction", ""),
            context=item["context"],
            expected=item["expected"],
        )
        for item in raw
    ]


# ── scoring ─────────────────────────────────────────────────────────────────
def flatten(obj: object, prefix: str = "") -> dict[str, object]:
    """Flatten a JSON value to {leaf_path: value}."""
    out: dict[str, object] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            out.update(flatten(value, f"{prefix}/{key}" if prefix else str(key)))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            out.update(flatten(value, f"{prefix}[{idx}]"))
    else:
        out[prefix or "<root>"] = obj
    return out


def _eq(a: object, b: object) -> bool:
    # Numbers compared numerically (150 == 150.0); строки — после strip.
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if isinstance(a, str) and isinstance(b, str):
        return a.strip() == b.strip()
    return a == b


@dataclass
class CaseScore:
    name: str
    valid_json: bool
    total: int          # scored fields (leaves in expected)
    matched: int
    extra: int          # leaves present in actual but not expected (hallucinations)
    attempts: int

    @property
    def field_accuracy(self) -> float:
        return self.matched / self.total if self.total else 0.0


def score_case(name: str, expected: dict, actual: Optional[dict], attempts: int) -> CaseScore:
    exp = flatten(expected)
    if actual is None:
        return CaseScore(name, False, len(exp), 0, 0, attempts)
    act = flatten(actual)
    matched = sum(1 for path, value in exp.items() if path in act and _eq(act[path], value))
    extra = sum(1 for path in act if path not in exp)
    return CaseScore(name, True, len(exp), matched, extra, attempts)


@dataclass
class BenchReport:
    cases: list[CaseScore] = field(default_factory=list)

    @property
    def total_fields(self) -> int:
        return sum(c.total for c in self.cases)

    @property
    def matched_fields(self) -> int:
        return sum(c.matched for c in self.cases)

    @property
    def field_accuracy_micro(self) -> float:  # like lift: matched/total over all fields
        return self.matched_fields / self.total_fields if self.total_fields else 0.0

    @property
    def field_accuracy_macro(self) -> float:  # mean of per-case accuracy
        return sum(c.field_accuracy for c in self.cases) / len(self.cases) if self.cases else 0.0

    @property
    def valid_json_rate(self) -> float:
        return sum(1 for c in self.cases if c.valid_json) / len(self.cases) if self.cases else 0.0

    @property
    def mean_attempts(self) -> float:
        return sum(c.attempts for c in self.cases) / len(self.cases) if self.cases else 0.0

    def as_dict(self) -> dict:
        return {
            "n_cases": len(self.cases),
            "scored_fields": self.total_fields,
            "field_accuracy_micro": round(self.field_accuracy_micro, 4),
            "field_accuracy_macro": round(self.field_accuracy_macro, 4),
            "valid_json_rate": round(self.valid_json_rate, 4),
            "mean_attempts": round(self.mean_attempts, 3),
            "cases": [
                {
                    "name": c.name,
                    "valid_json": c.valid_json,
                    "field_accuracy": round(c.field_accuracy, 4),
                    "matched": c.matched,
                    "total": c.total,
                    "extra": c.extra,
                    "attempts": c.attempts,
                }
                for c in self.cases
            ],
        }


def run_bench(
    cases: list[ExtractCase],
    call_llm: se.LLMCall,
    *,
    max_attempts: int = 3,
    use_cloud_response_format: bool = False,
) -> BenchReport:
    report = BenchReport()
    for case in cases:
        res = se.extract(
            case.schema,
            case.instruction,
            case.context,
            call_llm,
            max_attempts=max_attempts,
            use_cloud_response_format=use_cloud_response_format,
        )
        report.cases.append(score_case(case.name, case.expected, res.data, res.attempts))
    return report


# ── backends ────────────────────────────────────────────────────────────────
def echo_backend(cases: list[ExtractCase]) -> se.LLMCall:
    """Returns each case's expected JSON — harness self-test, no model.

    Identifies the case by the context embedded in the prompt (robust to order
    and retries), so a shared callable serves every case correctly.
    """
    by_context = [(c.context, json.dumps(c.expected, ensure_ascii=False)) for c in cases]

    def call(prompt: str, _rf: Optional[dict]) -> str:
        for context, reply in by_context:
            if context in prompt:
                return reply
        return "{}"

    return call


def http_backend(base_url: str, model: str, api_key: Optional[str] = None, timeout: float = 120.0) -> se.LLMCall:
    """OpenAI-compatible chat backend (local MLX or cloud)."""
    url = base_url.rstrip("/") + "/chat/completions"

    def call(prompt: str, response_format: Optional[dict]) -> str:
        body: dict = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024}
        if response_format is not None:
            body["response_format"] = response_format
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]

    return call


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Field-accuracy benchmark for schema-constrained extraction.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--backend", choices=("echo", "mlx", "cloud"), default="echo")
    parser.add_argument("--base-url", default=os.getenv("MLX_URL", "http://127.0.0.1:8080/v1"))
    parser.add_argument("--model", default=os.getenv("MLX_MODEL", ""))
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0, help="run only the first N cases")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    cases = load_cases(Path(args.cases))
    if args.limit:
        cases = cases[: args.limit]

    use_rf = False
    if args.backend == "echo":
        call_llm = echo_backend(cases)
    else:
        api_key = os.getenv(args.api_key_env) if args.backend == "cloud" else None
        call_llm = http_backend(args.base_url, args.model, api_key=api_key)
        use_rf = args.backend == "cloud"

    started = time.time()
    report = run_bench(cases, call_llm, max_attempts=args.max_attempts, use_cloud_response_format=use_rf)
    elapsed = time.time() - started
    result = report.as_dict()
    result["elapsed_sec"] = round(elapsed, 2)
    result["backend"] = args.backend

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"backend={args.backend}  cases={result['n_cases']}  fields={result['scored_fields']}")
        print(f"field_accuracy micro={result['field_accuracy_micro']:.1%}  macro={result['field_accuracy_macro']:.1%}")
        print(f"valid_json_rate={result['valid_json_rate']:.1%}  mean_attempts={result['mean_attempts']}  {elapsed:.1f}s")
        for c in result["cases"]:
            flag = "ok" if c["valid_json"] else "BAD"
            print(f"  [{flag}] {c['name']:<22} acc={c['field_accuracy']:.1%} ({c['matched']}/{c['total']}) extra={c['extra']} att={c['attempts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
