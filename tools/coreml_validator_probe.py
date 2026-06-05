"""Core ML validator conversion and probe helpers.

Converts a sequence-classification NLI/cross-encoder model into a fixed-shape
Core ML package for VALIDATOR_BACKEND=coreml. The runtime premise/hypothesis
format matches mlx_host.CoreMLValidator:

  premise    = context
  hypothesis = "Вопрос: ...\nОтвет: ..."
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import torch


os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_LABELS = ["ENTAILMENT", "NEUTRAL", "CONTRADICTION"]
DEFAULT_CANDIDATE_MODEL_ID = "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli"
DEFAULT_CANDIDATE_PACKAGE = "artifacts/coreml/validator_minilm_l6_b1_s512.mlpackage"
DEFAULT_CANDIDATE_MASK_RANK = 4
DEFAULT_CANDIDATE_COMPUTE_UNITS = "cpu_only"
VALID_STATUSES = {"VERIFIED", "NO_DATA", "HALLUCINATION"}

logger = logging.getLogger(__name__)


class ClassifierNoTokenTypes(torch.nn.Module):
    def __init__(self, model: torch.nn.Module):
        super().__init__()
        self.model = model

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        out = self.model(
            input_ids=input_ids.to(torch.long),
            attention_mask=attention_mask.to(torch.long),
            return_dict=False,
        )
        return out[0]


class ClassifierWithTokenTypes(torch.nn.Module):
    def __init__(self, model: torch.nn.Module):
        super().__init__()
        self.model = model

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        token_type_ids: torch.Tensor,
    ) -> torch.Tensor:
        out = self.model(
            input_ids=input_ids.to(torch.long),
            attention_mask=attention_mask.to(torch.long),
            token_type_ids=token_type_ids.to(torch.long),
            return_dict=False,
        )
        return out[0]


def _compute_unit(name: str):
    import coremltools as ct

    units = {
        "all": ct.ComputeUnit.ALL,
        "cpu_only": ct.ComputeUnit.CPU_ONLY,
        "cpu_and_gpu": ct.ComputeUnit.CPU_AND_GPU,
        "cpu_and_ne": ct.ComputeUnit.CPU_AND_NE,
    }
    return units[name]


def _compute_precision(name: str):
    import coremltools as ct

    values = {
        "float16": ct.precision.FLOAT16,
        "float32": ct.precision.FLOAT32,
    }
    return values[name]


def _labels_from_config(config: Any) -> list[str]:
    if getattr(config, "id2label", None):
        return [str(config.id2label[i]) for i in sorted(config.id2label)]
    return DEFAULT_LABELS


def _patch_deberta_scaled_sqrt() -> None:
    """Avoid a TorchScript int sqrt that coremltools cannot lower."""
    try:
        from transformers.models.deberta_v2 import modeling_deberta_v2
    except Exception:
        return

    def scaled_size_sqrt(query_layer: torch.Tensor, scale_factor: int):
        return torch.sqrt(query_layer.new_tensor(float(query_layer.size(-1) * scale_factor)))

    modeling_deberta_v2.scaled_size_sqrt = scaled_size_sqrt


def _hypothesis(question: str, answer: str, pair_mode: str = "answer") -> str:
    pair_mode = pair_mode.strip().lower()
    if pair_mode == "qa":
        return f"Вопрос: {question}\nОтвет: {answer}"
    if pair_mode == "answer":
        return answer or ""
    if pair_mode == "claim":
        return f'Ответ на вопрос "{question}": {answer}'
    raise ValueError("pair mode must be one of: answer, qa, claim")


def _pair(question: str, context: str, answer: str, pair_mode: str = "answer") -> tuple[str, str]:
    return context or "", _hypothesis(question, answer, pair_mode)


def _status_for_label(label: str) -> str:
    label = label.upper()
    if "ENTAIL" in label:
        return "VERIFIED"
    if "CONTRAD" in label:
        return "HALLUCINATION"
    return "NO_DATA"


def _softmax(logits: np.ndarray) -> np.ndarray:
    logits = logits.astype(np.float32)
    exp = np.exp(logits - np.max(logits))
    return exp / np.sum(exp)


def _attention_mask_array(mask: np.ndarray, rank: int) -> np.ndarray:
    mask = np.asarray(mask)
    if rank == 4:
        base = mask.astype(bool)
        return (base[:, None, None, :] & base[:, None, :, None]).astype(np.int32)
    return mask.astype(np.int32)


def _attention_mask_tensor(mask: torch.Tensor, rank: int) -> torch.Tensor:
    if rank == 4:
        base = mask.to(torch.bool)
        return (base[:, None, None, :] & base[:, None, :, None]).to(torch.int32)
    return mask.to(torch.int32)


def convert_validator(args: argparse.Namespace) -> dict[str, Any]:
    import coremltools as ct
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(args.model_id, local_files_only=args.local_files_only)
    _patch_deberta_scaled_sqrt()
    model_kwargs: dict[str, Any] = {"local_files_only": args.local_files_only}
    if args.attn_implementation:
        model_kwargs["attn_implementation"] = args.attn_implementation
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_id,
        **model_kwargs,
    ).eval().float()
    for param in model.parameters():
        param.requires_grad_(False)
    load_sec = time.perf_counter() - started

    premises: list[str] = []
    hypotheses: list[str] = []
    for _ in range(args.batch_size):
        premise, hypothesis = _pair(
            "Какая минимальная ширина прохода?",
            "Минимальная ширина прохода 0,8 м.",
            "Минимальная ширина прохода 0,8 м.",
        )
        premises.append(premise)
        hypotheses.append(hypothesis)

    tokens = tokenizer(
        premises,
        hypotheses,
        padding="max_length",
        truncation=True,
        max_length=args.seq_len,
        return_tensors="pt",
    )
    input_ids = tokens["input_ids"].to(torch.int32)
    attention_mask = _attention_mask_tensor(tokens["attention_mask"], args.attention_mask_rank)
    uses_token_types = "token_type_ids" in tokens

    if uses_token_types:
        token_type_ids = tokens["token_type_ids"].to(torch.int32)
        wrapper = ClassifierWithTokenTypes(model).eval()
        trace_inputs = (input_ids, attention_mask, token_type_ids)
        convert_inputs = [
            ct.TensorType(name="input_ids", shape=input_ids.shape, dtype=np.int32),
            ct.TensorType(name="attention_mask", shape=attention_mask.shape, dtype=np.int32),
            ct.TensorType(name="token_type_ids", shape=token_type_ids.shape, dtype=np.int32),
        ]
    else:
        wrapper = ClassifierNoTokenTypes(model).eval()
        trace_inputs = (input_ids, attention_mask)
        convert_inputs = [
            ct.TensorType(name="input_ids", shape=input_ids.shape, dtype=np.int32),
            ct.TensorType(name="attention_mask", shape=attention_mask.shape, dtype=np.int32),
        ]

    with torch.no_grad():
        torch_logits = wrapper(*trace_inputs).float()
        traced = torch.jit.trace(wrapper, trace_inputs, strict=False)
        traced_logits = traced(*trace_inputs).float()

    started = time.perf_counter()
    mlmodel = ct.convert(
        traced,
        convert_to="mlprogram",
        inputs=convert_inputs,
        outputs=[ct.TensorType(name="logits")],
        compute_precision=_compute_precision(args.compute_precision),
        minimum_deployment_target=ct.target.macOS14,
    )
    mlmodel.user_defined_metadata["labels"] = json.dumps(_labels_from_config(model.config), ensure_ascii=False)
    mlmodel.save(str(output))
    convert_sec = time.perf_counter() - started

    cosine = torch.nn.functional.cosine_similarity(torch_logits, traced_logits, dim=1).mean().item()
    return {
        "status": "converted",
        "model_id": args.model_id,
        "output": output.as_posix(),
        "batch_size": args.batch_size,
        "seq_len": args.seq_len,
        "attention_mask_rank": args.attention_mask_rank,
        "labels": _labels_from_config(model.config),
        "uses_token_type_ids": uses_token_types,
        "compute_precision": args.compute_precision,
        "load_sec": round(load_sec, 3),
        "convert_sec": round(convert_sec, 3),
        "cosine_vs_trace": cosine,
    }


def _probe_cases() -> list[dict[str, str]]:
    return [
        {
            "id": "width_verified",
            "question": "Какая минимальная ширина прохода?",
            "context": "Минимальная ширина прохода 0,8 м.",
            "answer": "Минимальная ширина прохода 0,8 м.",
            "expected": "VERIFIED",
        },
        {
            "id": "width_contradiction",
            "question": "Какая минимальная ширина прохода?",
            "context": "Минимальная ширина прохода 0,8 м.",
            "answer": "Минимальная ширина прохода 1,2 м.",
            "expected": "HALLUCINATION",
        },
        {
            "id": "retention_no_data",
            "question": "Какой срок хранения документа?",
            "context": "Минимальная ширина прохода 0,8 м.",
            "answer": "Срок хранения составляет 5 лет.",
            "expected": "NO_DATA",
        },
    ]


def load_cases(path: str | Path | None = None) -> list[dict[str, str]]:
    if not path:
        raw_cases: Any = _probe_cases()
    else:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_cases = raw.get("cases", raw) if isinstance(raw, dict) else raw
    if not isinstance(raw_cases, list):
        raise ValueError("case file must be a list or an object with a 'cases' list")

    cases: list[dict[str, str]] = []
    for index, item in enumerate(raw_cases, 1):
        if not isinstance(item, dict):
            raise ValueError(f"case #{index} must be an object")
        case = dict(item)
        case.update({
            "id": str(item.get("id") or f"case_{index:03d}"),
            "expected": str(item.get("expected") or "").strip().upper(),
            "question": str(item.get("question") or ""),
            "context": str(item.get("context") or ""),
            "answer": str(item.get("answer") or ""),
        })
        if case["expected"] and case["expected"] not in VALID_STATUSES:
            raise ValueError(f"case {case['id']} has invalid expected={case['expected']!r}")
        if not case["question"]:
            raise ValueError(f"case {case['id']} is missing question")
        if not case["answer"]:
            raise ValueError(f"case {case['id']} is missing answer")
        cases.append(case)
    return cases


def _first_array(payload: dict[str, Any]) -> np.ndarray:
    preferred = ("logits", "scores", "output", "var_0")
    for key in preferred:
        if key in payload:
            return np.asarray(payload[key], dtype=np.float32)
    for value in payload.values():
        arr = np.asarray(value, dtype=np.float32)
        if arr.size:
            return arr
    raise ValueError("Core ML validator returned no numeric outputs")


def _apply_confidence_threshold(status: str, score: float | None, threshold: float) -> tuple[str, bool]:
    if threshold <= 0 or score is None or score >= threshold:
        return status, False
    return "NO_DATA", True


def _rules_validate(case: dict[str, str]) -> dict[str, Any]:
    import re

    def normalize(text: str) -> str:
        return " ".join(re.sub(r"[^\w]+", " ", text.lower(), flags=re.UNICODE).split())

    def numbers(text: str) -> set[str]:
        return {match.group(0).replace(",", ".") for match in re.finditer(r"\d+(?:[,.]\d+)?", text)}

    context = case.get("context") or ""
    answer = case.get("answer") or ""
    if not context.strip():
        return {"status": "NO_DATA", "raw": "empty_context", "score": None}
    if answer.strip() and normalize(answer) in normalize(context):
        return {"status": "VERIFIED", "raw": "answer_text_found_in_context", "score": None}
    answer_numbers = numbers(answer)
    context_numbers = numbers(context)
    if answer_numbers and context_numbers and not answer_numbers.issubset(context_numbers):
        return {"status": "HALLUCINATION", "raw": "answer_numeric_claim_not_in_context", "score": None}
    return {"status": "NO_DATA", "raw": "rules_cannot_verify", "score": None}


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 90.0,
) -> tuple[int, dict[str, Any], str]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw or "{}"), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw or "{}")
        except json.JSONDecodeError:
            body = {"error": raw}
        return exc.code, body, raw
    except OSError as exc:
        return 0, {"error": str(exc)}, str(exc)


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = [row for row in rows if row.get("status") != "SKIPPED"]
    correct = sum(1 for row in attempted if row.get("ok"))
    latencies = [float(row["latency_sec"]) for row in attempted if row.get("latency_sec") is not None]
    summary = {
        "total": len(rows),
        "attempted": len(attempted),
        "skipped": len(rows) - len(attempted),
        "correct": correct,
        "accuracy": round(correct / len(attempted), 4) if attempted else None,
        "latency_mean_sec": round(sum(latencies) / len(latencies), 4) if latencies else None,
        "latency_max_sec": round(max(latencies), 4) if latencies else None,
        "by_expected": {},
    }
    by_expected: dict[str, dict[str, int]] = {}
    for row in attempted:
        expected = str(row.get("expected") or "")
        bucket = by_expected.setdefault(expected, {"total": 0, "correct": 0})
        bucket["total"] += 1
        if row.get("ok"):
            bucket["correct"] += 1
    summary["by_expected"] = {
        key: {
            **value,
            "accuracy": round(value["correct"] / value["total"], 4) if value["total"] else None,
        }
        for key, value in sorted(by_expected.items())
    }
    return summary


def _threshold_sweep(rows: list[dict[str, Any]], thresholds: list[float]) -> list[dict[str, Any]]:
    sweep = []
    coreml_rows = [row for row in rows if row.get("backend") == "coreml" and row.get("status") != "SKIPPED"]
    for threshold in thresholds:
        threshold_rows = []
        for row in coreml_rows:
            adjusted, thresholded = _apply_confidence_threshold(
                str(row.get("actual") or ""),
                row.get("score") if isinstance(row.get("score"), (int, float)) else None,
                threshold,
            )
            threshold_rows.append({
                **row,
                "actual": adjusted,
                "ok": adjusted == row.get("expected"),
                "confidence_thresholded": thresholded,
            })
        item = _summarize_rows(threshold_rows)
        item["threshold"] = threshold
        sweep.append(item)
    return sweep


async def _cases_with_rag_validation_contexts(args: argparse.Namespace, cases: list[dict[str, str]]) -> list[dict[str, Any]]:
    from backend.qdrant_adapter import QdrantLlamaIndexAdapter
    from backend.rag_config import embedding_api_model
    from proxy.services.context_expander_service import expand_context_windows
    from proxy.services.retrieval_service import classify_query, resolve_dataset_ids, retrieve_chat_chunks
    from proxy.services.saferag_service import build_validation_context, concentrate_sources, rank_chunks_for_question

    rag_backend = QdrantLlamaIndexAdapter(
        qdrant_url=args.qdrant_url,
        mlx_url=args.mlx_url,
        embed_model_name=args.embed_model or embedding_api_model(),
    )
    materialized: list[dict[str, Any]] = []
    for case in cases:
        question = case["question"]
        route = classify_query(question)
        dataset_filter = case.get("dataset_filter") or route.dataset_filter
        dataset_ids = await resolve_dataset_ids(
            rag_backend,
            None,
            dataset_filter,
            logger,
            question=question,
        )
        retrieval = await retrieve_chat_chunks(
            question=question,
            dataset_ids=dataset_ids,
            rag_backend=rag_backend,
            reranker_enabled=False,
            reranker_available=False,
            reranker_cls=None,
            mlx_url=args.mlx_url,
            logger=logger,
            return_trace=True,
        )
        chunks = rank_chunks_for_question(question, retrieval.chunks)
        chunks = concentrate_sources(
            chunks,
            max_docs=args.focus_max_docs,
            min_score=args.focus_min_score,
            max_chunks=args.focus_max_chunks,
        )
        windows = expand_context_windows(
            chunks,
            collection=getattr(rag_backend, "collection_name", ""),
            logger=logger,
            max_chunks=args.validation_max_chunks,
            max_chars_per_chunk=args.validation_window_chars,
            radius=args.validation_radius,
        )
        context = build_validation_context(
            windows.chunks,
            max_chars=args.validation_context_chars,
            include_metadata=True,
        )
        materialized.append({
            **case,
            "context": context,
            "context_source": "validation_context_windows",
            "retrieval_trace": retrieval.payload(),
            "validation_context_window": windows.payload(),
            "sources": [getattr(chunk, "doc_name", "") for chunk in windows.chunks],
        })
    return materialized


def _parse_thresholds(value: str) -> list[float]:
    thresholds = []
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        thresholds.append(float(raw))
    return thresholds or [0.0]


def _context_windows(context: str, context_mode: str) -> list[str]:
    context = context or ""
    context_mode = context_mode.strip().lower()
    if context_mode == "full":
        return [context]
    if context_mode != "windows":
        raise ValueError("context mode must be one of: full, windows")
    parts = re.split(r"(?=\[Источник\s+\d+\s+\|)", context)
    windows = [part.strip() for part in parts if part.strip()]
    return windows or [context]


def _predict_coreml_window(
    *,
    tokenizer,
    mlmodel,
    labels: list[str],
    premise: str,
    hypothesis: str,
    seq_len: int,
    attention_mask_rank: int,
) -> dict[str, Any]:
    tokens = tokenizer(
        premise,
        hypothesis,
        padding="max_length",
        truncation=True,
        max_length=seq_len,
        return_tensors="np",
    )
    payload = {
        "input_ids": tokens["input_ids"].astype(np.int32),
        "attention_mask": _attention_mask_array(tokens["attention_mask"], attention_mask_rank),
    }
    if "token_type_ids" in tokens:
        payload["token_type_ids"] = tokens["token_type_ids"].astype(np.int32)
    result = mlmodel.predict(payload)
    logits = _first_array(result).reshape(-1)
    probs = _softmax(logits[: len(labels)])
    index = int(np.argmax(probs))
    label = labels[index]
    scores_by_status = {"VERIFIED": 0.0, "NO_DATA": 0.0, "HALLUCINATION": 0.0}
    for idx, mapped_label in enumerate(labels):
        mapped_status = _status_for_label(mapped_label)
        scores_by_status[mapped_status] = max(scores_by_status[mapped_status], float(probs[idx]))
    return {
        "label": label,
        "status": _status_for_label(label),
        "score": float(probs[index]),
        "scores_by_status": scores_by_status,
    }


def _coreml_decision(max_scores: dict[str, float], args: argparse.Namespace) -> tuple[str, str, float]:
    entailment_score = max_scores.get("VERIFIED", 0.0)
    contradiction_score = max_scores.get("HALLUCINATION", 0.0)
    margin = max(0.0, float(args.decision_margin))
    if (
        entailment_score >= float(args.entailment_threshold)
        and entailment_score >= contradiction_score + margin
    ):
        return "VERIFIED", "WINDOW_ENTAILMENT", entailment_score
    if (
        contradiction_score >= float(args.contradiction_threshold)
        and contradiction_score >= entailment_score + margin
    ):
        return "HALLUCINATION", "WINDOW_CONTRADICTION", contradiction_score
    return "NO_DATA", "WINDOW_UNCERTAIN", max(max_scores.values())


def _predict_coreml_case(
    *,
    tokenizer,
    mlmodel,
    labels: list[str],
    case: dict[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    hypothesis = _hypothesis(case["question"], case["answer"], args.pair_mode)
    window_results = [
        _predict_coreml_window(
            tokenizer=tokenizer,
            mlmodel=mlmodel,
            labels=labels,
            premise=window,
            hypothesis=hypothesis,
            seq_len=args.seq_len,
            attention_mask_rank=args.attention_mask_rank,
        )
        for window in _context_windows(case.get("context") or "", args.context_mode)
    ]
    max_scores = {"VERIFIED": 0.0, "NO_DATA": 0.0, "HALLUCINATION": 0.0}
    for result in window_results:
        for status_name, score_value in result["scores_by_status"].items():
            max_scores[status_name] = max(max_scores[status_name], score_value)
    status, raw, score = _coreml_decision(max_scores, args)
    return {
        "status": status,
        "raw": raw,
        "score": score,
        "scores": max_scores,
        "window_count": len(window_results),
    }


def probe_coreml(args: argparse.Namespace) -> dict[str, Any]:
    import coremltools as ct
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=args.local_files_only)
    mlmodel = ct.models.MLModel(args.coreml_model, compute_units=_compute_unit(args.compute_units))
    labels = [label.strip() for label in args.labels.split(",") if label.strip()]
    rows = []
    started = time.perf_counter()
    cases = load_cases(args.cases)
    for case in cases:
        case_started = time.perf_counter()
        result = _predict_coreml_case(
            tokenizer=tokenizer,
            mlmodel=mlmodel,
            labels=labels,
            case=case,
            args=args,
        )
        rows.append({
            "id": case["id"],
            "expected": case["expected"],
            "label": result["raw"],
            "status": result["status"],
            "ok": result["status"] == case["expected"],
            "score": result["score"],
            "scores": result["scores"],
            "window_count": result["window_count"],
            "latency_sec": round(time.perf_counter() - case_started, 4),
        })
    elapsed = time.perf_counter() - started
    return {
        "status": "probed",
        "coreml_model": args.coreml_model,
        "seq_len": args.seq_len,
        "compute_units": args.compute_units,
        "attention_mask_rank": args.attention_mask_rank,
        "context_mode": args.context_mode,
        "pair_mode": args.pair_mode,
        "entailment_threshold": args.entailment_threshold,
        "contradiction_threshold": args.contradiction_threshold,
        "decision_margin": args.decision_margin,
        "cases": rows,
        "summary": _summarize_rows([
            {
                "expected": row["expected"],
                "actual": row["status"],
                "ok": row["ok"],
                "latency_sec": row["latency_sec"],
            }
            for row in rows
        ]),
        "elapsed_sec": round(elapsed, 3),
    }


def _coreml_runner(args: argparse.Namespace):
    if not Path(args.coreml_model).exists():
        if args.require_coreml:
            raise FileNotFoundError(f"Core ML validator package not found: {args.coreml_model}")
        return None

    import coremltools as ct
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=args.local_files_only)
    mlmodel = ct.models.MLModel(args.coreml_model, compute_units=_compute_unit(args.compute_units))
    labels = [label.strip() for label in args.labels.split(",") if label.strip()]

    def run(case: dict[str, str]) -> dict[str, Any]:
        return _predict_coreml_case(
            tokenizer=tokenizer,
            mlmodel=mlmodel,
            labels=labels,
            case=case,
            args=args,
        )

    return run


def compare_backends(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_cases(args.cases)
    context_source = "case_context"
    if args.use_rag_context_windows:
        cases = asyncio.run(_cases_with_rag_validation_contexts(args, cases))
        context_source = "validation_context_windows"
        if args.materialized_cases:
            output_path = Path(args.materialized_cases)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "version": "v1",
                        "description": "Validator golden cases materialized with real validation_context_windows.",
                        "cases": cases,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    backends = [item.strip().lower() for item in args.backends.split(",") if item.strip()]
    rows: list[dict[str, Any]] = []
    coreml_run = None
    if "coreml" in backends:
        coreml_run = _coreml_runner(args)

    for case in cases:
        for backend in backends:
            started = time.perf_counter()
            expected = case.get("expected") or ""
            try:
                if backend == "rules":
                    result = _rules_validate(case)
                elif backend == "coreml":
                    if coreml_run is None:
                        rows.append({
                            "id": case["id"],
                            "backend": backend,
                            "expected": expected,
                            "actual": "",
                            "status": "SKIPPED",
                            "ok": False,
                            "latency_sec": None,
                            "error": f"missing Core ML package: {args.coreml_model}",
                        })
                        continue
                    result = coreml_run(case)
                elif backend == "mlx":
                    http_status, payload, raw = _request_json(
                        "POST",
                        f"{args.mlx_url.rstrip('/')}/api/validate",
                        payload={
                            "question": case["question"],
                            "answer": case["answer"],
                            "context": case["context"],
                        },
                        timeout=args.timeout,
                    )
                    if http_status != 200:
                        raise RuntimeError(f"HTTP {http_status}: {raw[:300]}")
                    result = payload
                else:
                    raise ValueError(f"unknown backend: {backend}")
                actual = str(result.get("status") or "")
                score = result.get("score")
                rows.append({
                    "id": case["id"],
                    "backend": backend,
                    "expected": expected,
                    "actual": actual,
                    "status": "OK",
                    "ok": actual == expected if expected else None,
                    "raw": result.get("raw", ""),
                    "score": score if isinstance(score, (int, float)) else None,
                    "latency_sec": round(time.perf_counter() - started, 4),
                    "context_chars": len(case.get("context") or ""),
                })
            except Exception as error:
                rows.append({
                    "id": case["id"],
                    "backend": backend,
                    "expected": expected,
                    "actual": "",
                    "status": "ERROR",
                    "ok": False,
                    "latency_sec": round(time.perf_counter() - started, 4),
                    "error": str(error),
                })

    by_backend = {
        backend: _summarize_rows([row for row in rows if row.get("backend") == backend])
        for backend in backends
    }
    thresholds = _parse_thresholds(args.thresholds)
    report = {
        "status": "benchmarked",
        "context_source": context_source,
        "cases": len(cases),
        "backends": backends,
        "coreml_model": args.coreml_model,
        "tokenizer": args.tokenizer,
        "seq_len": args.seq_len,
        "attention_mask_rank": args.attention_mask_rank,
        "context_mode": args.context_mode,
        "pair_mode": args.pair_mode,
        "entailment_threshold": args.entailment_threshold,
        "contradiction_threshold": args.contradiction_threshold,
        "decision_margin": args.decision_margin,
        "labels": [label.strip() for label in args.labels.split(",") if label.strip()],
        "summary": by_backend,
        "coreml_threshold_sweep": _threshold_sweep(rows, thresholds),
        "rows": rows,
    }
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Core ML validator conversion.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    convert = sub.add_parser("convert", help="Convert NLI/cross-encoder classifier to fixed-shape Core ML.")
    convert.add_argument("--model-id", default=DEFAULT_CANDIDATE_MODEL_ID)
    convert.add_argument("--output", default=DEFAULT_CANDIDATE_PACKAGE)
    convert.add_argument("--seq-len", type=int, default=512)
    convert.add_argument("--batch-size", type=int, default=1)
    convert.add_argument("--attention-mask-rank", type=int, choices=[2, 4], default=DEFAULT_CANDIDATE_MASK_RANK)
    convert.add_argument("--compute-precision", choices=["float16", "float32"], default="float16")
    convert.add_argument("--attn-implementation", default="eager")
    convert.add_argument("--local-files-only", action="store_true")
    convert.set_defaults(func=convert_validator)

    probe = sub.add_parser("probe", help="Run smoke cases against a converted Core ML validator.")
    probe.add_argument("--coreml-model", default=DEFAULT_CANDIDATE_PACKAGE)
    probe.add_argument("--tokenizer", default=DEFAULT_CANDIDATE_MODEL_ID)
    probe.add_argument("--seq-len", type=int, default=512)
    probe.add_argument("--attention-mask-rank", type=int, choices=[2, 4], default=DEFAULT_CANDIDATE_MASK_RANK)
    probe.add_argument("--context-mode", choices=["full", "windows"], default="windows")
    probe.add_argument("--pair-mode", choices=["answer", "qa", "claim"], default="answer")
    probe.add_argument("--entailment-threshold", type=float, default=0.8)
    probe.add_argument("--contradiction-threshold", type=float, default=0.6)
    probe.add_argument("--decision-margin", type=float, default=0.05)
    probe.add_argument(
        "--compute-units",
        choices=["all", "cpu_only", "cpu_and_gpu", "cpu_and_ne"],
        default=DEFAULT_CANDIDATE_COMPUTE_UNITS,
    )
    probe.add_argument("--labels", default="ENTAILMENT,NEUTRAL,CONTRADICTION")
    probe.add_argument("--cases", default="", help="Golden case JSON; defaults to built-in smoke cases.")
    probe.add_argument("--local-files-only", action="store_true")
    probe.set_defaults(func=probe_coreml)

    compare = sub.add_parser("compare", help="Compare mlx/coreml/rules validator backends on golden cases.")
    compare.add_argument("--cases", default="golden/validator_probe_set.json")
    compare.add_argument("--backends", default="rules,coreml,mlx")
    compare.add_argument("--mlx-url", default="http://127.0.0.1:8080")
    compare.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    compare.add_argument("--embed-model", default="")
    compare.add_argument("--coreml-model", default=DEFAULT_CANDIDATE_PACKAGE)
    compare.add_argument("--tokenizer", default=DEFAULT_CANDIDATE_MODEL_ID)
    compare.add_argument("--seq-len", type=int, default=512)
    compare.add_argument("--attention-mask-rank", type=int, choices=[2, 4], default=DEFAULT_CANDIDATE_MASK_RANK)
    compare.add_argument("--context-mode", choices=["full", "windows"], default="windows")
    compare.add_argument("--pair-mode", choices=["answer", "qa", "claim"], default="answer")
    compare.add_argument("--entailment-threshold", type=float, default=0.8)
    compare.add_argument("--contradiction-threshold", type=float, default=0.6)
    compare.add_argument("--decision-margin", type=float, default=0.05)
    compare.add_argument(
        "--compute-units",
        choices=["all", "cpu_only", "cpu_and_gpu", "cpu_and_ne"],
        default=DEFAULT_CANDIDATE_COMPUTE_UNITS,
    )
    compare.add_argument("--labels", default="ENTAILMENT,NEUTRAL,CONTRADICTION")
    compare.add_argument("--thresholds", default="0,0.5,0.6,0.7,0.8,0.9")
    compare.add_argument("--timeout", type=float, default=90.0)
    compare.add_argument("--local-files-only", action="store_true")
    compare.add_argument("--require-coreml", action="store_true")
    compare.add_argument("--use-rag-context-windows", action="store_true")
    compare.add_argument("--materialized-cases", default="")
    compare.add_argument("--output", default="")
    compare.add_argument("--focus-max-docs", type=int, default=int(os.getenv("RAG_CHAT_FOCUS_MAX_DOCS", "3")))
    compare.add_argument("--focus-min-score", type=float, default=float(os.getenv("RAG_CHAT_FOCUS_MIN_SCORE", "0.35")))
    compare.add_argument("--focus-max-chunks", type=int, default=int(os.getenv("RAG_CHAT_FOCUS_MAX_CHUNKS", "8")))
    compare.add_argument("--validation-max-chunks", type=int, default=int(os.getenv("RAG_VALIDATION_CONTEXT_MAX_CHUNKS", "10")))
    compare.add_argument("--validation-window-chars", type=int, default=int(os.getenv("RAG_VALIDATION_CONTEXT_WINDOW_CHARS", "2600")))
    compare.add_argument("--validation-radius", type=int, default=int(os.getenv("RAG_VALIDATION_CONTEXT_RADIUS", "1")))
    compare.add_argument("--validation-context-chars", type=int, default=int(os.getenv("RAG_VALIDATION_CONTEXT_CHARS", "12000")))
    compare.set_defaults(func=compare_backends)

    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
