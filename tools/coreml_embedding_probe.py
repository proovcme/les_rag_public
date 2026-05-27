"""Core ML embedding conversion and benchmark probes.

Conversion/bench tooling for the guarded MLX Host Core ML embedding backend.
Bench commands keep Qdrant untouched and sample texts from SQLite/storage.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.mail_profile import build_mail_vector_profile


os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


class BertMeanPoolNormalizeStatic(torch.nn.Module):
    """BERT-like encoder path that avoids Transformers 5.x masking helpers."""

    def __init__(self, bert: torch.nn.Module, batch_size: int, seq_len: int):
        super().__init__()
        self.embeddings = bert.embeddings
        self.encoder = bert.encoder
        self.register_buffer(
            "position_ids",
            torch.arange(seq_len, dtype=torch.long).unsqueeze(0).expand(batch_size, -1),
            persistent=False,
        )
        self.register_buffer(
            "token_type_ids",
            torch.zeros((batch_size, seq_len), dtype=torch.long),
            persistent=False,
        )

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        hidden = self.embeddings(
            input_ids=input_ids,
            position_ids=self.position_ids,
            token_type_ids=self.token_type_ids,
        )
        mask_f = attention_mask[:, None, None, :].to(dtype=hidden.dtype)
        extended = (1.0 - mask_f) * -10000.0
        encoded = self.encoder(hidden, attention_mask=extended, return_dict=False)[0]
        pool_mask = attention_mask.unsqueeze(-1).to(encoded.dtype)
        pooled = (encoded * pool_mask).sum(dim=1) / torch.clamp(pool_mask.sum(dim=1), min=1e-9)
        return F.normalize(pooled, p=2, dim=1)


class QwenLastTokenNormalizeStatic(torch.nn.Module):
    """Qwen3 embedding path with static RoPE and causal mask buffers."""

    def __init__(self, qwen: torch.nn.Module, batch_size: int, seq_len: int):
        super().__init__()
        self.embed_tokens = qwen.embed_tokens
        self.layers = qwen.layers
        self.norm = qwen.norm

        config = qwen.config
        self.num_attention_heads = config.num_attention_heads
        self.num_key_value_heads = config.num_key_value_heads
        self.num_key_value_groups = config.num_attention_heads // config.num_key_value_heads
        self.head_dim = getattr(config, "head_dim", config.hidden_size // config.num_attention_heads)
        self.half_head_dim = self.head_dim // 2
        self.hidden_size = config.hidden_size
        self.attn_output_size = config.num_attention_heads * self.head_dim
        self.batch_size = batch_size
        self.seq_len = seq_len

        position_ids = torch.arange(seq_len, dtype=torch.long).unsqueeze(0).expand(batch_size, -1)
        self.register_buffer("position_ids", position_ids, persistent=False)

        causal = torch.triu(torch.ones((seq_len, seq_len), dtype=torch.float32), diagonal=1) * -10000.0
        self.register_buffer("causal_mask", causal.view(1, 1, seq_len, seq_len), persistent=False)

        inv_freq = qwen.rotary_emb.inv_freq.float()
        freqs = torch.einsum("bs,d->bsd", position_ids.float(), inv_freq)
        emb = torch.cat((freqs, freqs), dim=-1)
        self.register_buffer("rotary_cos", emb.cos(), persistent=False)
        self.register_buffer("rotary_sin", emb.sin(), persistent=False)

    def _rotate_half(self, x: torch.Tensor) -> torch.Tensor:
        x1 = x[..., : self.half_head_dim]
        x2 = x[..., self.half_head_dim :]
        return torch.cat((-x2, x1), dim=-1)

    def _apply_rope(
        self,
        query: torch.Tensor,
        key: torch.Tensor,
        hidden_states: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        cos = self.rotary_cos.to(dtype=hidden_states.dtype).unsqueeze(1)
        sin = self.rotary_sin.to(dtype=hidden_states.dtype).unsqueeze(1)
        query = (query * cos) + (self._rotate_half(query) * sin)
        key = (key * cos) + (self._rotate_half(key) * sin)
        return query, key

    def _repeat_kv(self, hidden_states: torch.Tensor) -> torch.Tensor:
        if self.num_key_value_groups == 1:
            return hidden_states
        hidden_states = hidden_states[:, :, None, :, :].expand(
            self.batch_size,
            self.num_key_value_heads,
            self.num_key_value_groups,
            self.seq_len,
            self.head_dim,
        )
        return hidden_states.reshape(self.batch_size, self.num_attention_heads, self.seq_len, self.head_dim)

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        hidden_states = self.embed_tokens(input_ids)
        pad_mask = (1.0 - attention_mask[:, None, None, :].to(dtype=hidden_states.dtype)) * -10000.0
        attention_bias = self.causal_mask.to(dtype=hidden_states.dtype) + pad_mask

        for layer in self.layers:
            residual = hidden_states
            states = layer.input_layernorm(hidden_states)
            attn = layer.self_attn

            query = attn.q_norm(
                attn.q_proj(states).view(self.batch_size, self.seq_len, self.num_attention_heads, self.head_dim)
            ).transpose(1, 2)
            key = attn.k_norm(
                attn.k_proj(states).view(self.batch_size, self.seq_len, self.num_key_value_heads, self.head_dim)
            ).transpose(1, 2)
            value = attn.v_proj(states).view(
                self.batch_size,
                self.seq_len,
                self.num_key_value_heads,
                self.head_dim,
            ).transpose(1, 2)

            query, key = self._apply_rope(query, key, states)
            key = self._repeat_kv(key)
            value = self._repeat_kv(value)

            weights = torch.matmul(query, key.transpose(2, 3)) * attn.scaling
            weights = weights + attention_bias
            weights = F.softmax(weights, dim=-1, dtype=torch.float32).to(dtype=query.dtype)
            attn_output = torch.matmul(weights, value)
            attn_output = attn_output.transpose(1, 2).contiguous().reshape(
                self.batch_size,
                self.seq_len,
                self.attn_output_size,
            )

            hidden_states = residual + attn.o_proj(attn_output)
            residual = hidden_states
            hidden_states = residual + layer.mlp(layer.post_attention_layernorm(hidden_states))

        hidden_states = self.norm(hidden_states)
        last_indices = (torch.clamp(attention_mask.sum(dim=1), min=1) - 1).to(torch.long)
        gather_indices = last_indices.view(self.batch_size, 1, 1).expand(self.batch_size, 1, self.hidden_size)
        pooled = torch.gather(hidden_states, 1, gather_indices).squeeze(1)
        return F.normalize(pooled, p=2, dim=1)


def _compute_unit(name: str):
    import coremltools as ct

    units = {
        "all": ct.ComputeUnit.ALL,
        "cpu_only": ct.ComputeUnit.CPU_ONLY,
        "cpu_and_gpu": ct.ComputeUnit.CPU_AND_GPU,
        "cpu_and_ne": ct.ComputeUnit.CPU_AND_NE,
    }
    return units[name]


def convert_e5(args: argparse.Namespace) -> dict[str, Any]:
    import coremltools as ct

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    model = SentenceTransformer(args.model_id, device="cpu")
    bert = model[0].auto_model.eval()
    for param in bert.parameters():
        param.requires_grad_(False)
    load_sec = time.perf_counter() - started

    tokenizer = model.tokenizer
    sample_texts = ["query: Core ML embedding conversion smoke"] * args.batch_size
    tokens = tokenizer(
        sample_texts,
        padding="max_length",
        truncation=True,
        max_length=args.seq_len,
        return_tensors="pt",
    )
    input_ids = tokens["input_ids"].to(torch.int32)
    attention_mask = tokens["attention_mask"].to(torch.int32)
    wrapper = BertMeanPoolNormalizeStatic(bert, args.batch_size, args.seq_len).eval()

    with torch.no_grad():
        torch_vec = wrapper(input_ids, attention_mask)
        traced = torch.jit.trace(wrapper, (input_ids, attention_mask), strict=False)

    started = time.perf_counter()
    mlmodel = ct.convert(
        traced,
        convert_to="mlprogram",
        inputs=[
            ct.TensorType(name="input_ids", shape=input_ids.shape, dtype=np.int32),
            ct.TensorType(name="attention_mask", shape=attention_mask.shape, dtype=np.int32),
        ],
        outputs=[ct.TensorType(name="embeddings")],
        compute_precision=ct.precision.FLOAT16,
        minimum_deployment_target=ct.target.macOS14,
    )
    convert_sec = time.perf_counter() - started
    mlmodel.save(str(output))

    return {
        "status": "converted",
        "model_id": args.model_id,
        "output": output.as_posix(),
        "batch_size": args.batch_size,
        "seq_len": args.seq_len,
        "embedding_dim": int(torch_vec.shape[1]),
        "load_sec": round(load_sec, 3),
        "convert_sec": round(convert_sec, 3),
    }


def convert_qwen(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    model = SentenceTransformer(args.model_id, device="cpu")
    qwen = model[0].auto_model.eval().to(dtype=torch.float32)
    for param in qwen.parameters():
        param.requires_grad_(False)
    load_sec = time.perf_counter() - started

    tokenizer = model.tokenizer
    sample_texts = ["query: Core ML Qwen embedding conversion smoke"] * args.batch_size
    tokens = tokenizer(
        sample_texts,
        padding="max_length",
        truncation=True,
        max_length=args.seq_len,
        return_tensors="pt",
    )
    input_ids = tokens["input_ids"].to(torch.int32)
    attention_mask = tokens["attention_mask"].to(torch.int32)
    wrapper = QwenLastTokenNormalizeStatic(qwen, args.batch_size, args.seq_len).eval()

    with torch.no_grad():
        torch_vec = wrapper(input_ids, attention_mask).float()
        st_vec = model.encode(
            sample_texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=args.batch_size,
        ).astype(np.float32)
        traced = torch.jit.trace(wrapper, (input_ids, attention_mask), strict=False)
        traced_vec = traced(input_ids, attention_mask).float()

    cosine_vs_st = float(F.cosine_similarity(torch_vec, torch.from_numpy(st_vec), dim=1).mean())
    cosine_vs_trace = float(F.cosine_similarity(torch_vec, traced_vec, dim=1).mean())

    if args.trace_only:
        return {
            "status": "traced",
            "model_id": args.model_id,
            "batch_size": args.batch_size,
            "seq_len": args.seq_len,
            "embedding_dim": int(torch_vec.shape[1]),
            "load_sec": round(load_sec, 3),
            "cosine_vs_sentence_transformers": cosine_vs_st,
            "cosine_vs_trace": cosine_vs_trace,
        }

    import coremltools as ct

    started = time.perf_counter()
    mlmodel = ct.convert(
        traced,
        convert_to="mlprogram",
        inputs=[
            ct.TensorType(name="input_ids", shape=input_ids.shape, dtype=np.int32),
            ct.TensorType(name="attention_mask", shape=attention_mask.shape, dtype=np.int32),
        ],
        outputs=[ct.TensorType(name="embeddings")],
        compute_precision=ct.precision.FLOAT16,
        minimum_deployment_target=ct.target.macOS14,
    )
    convert_sec = time.perf_counter() - started
    mlmodel.save(str(output))

    return {
        "status": "converted",
        "model_id": args.model_id,
        "output": output.as_posix(),
        "batch_size": args.batch_size,
        "seq_len": args.seq_len,
        "embedding_dim": int(torch_vec.shape[1]),
        "load_sec": round(load_sec, 3),
        "convert_sec": round(convert_sec, 3),
        "cosine_vs_sentence_transformers": cosine_vs_st,
        "cosine_vs_trace": cosine_vs_trace,
    }


def _mail_dataset(db_path: Path, dataset_name: str) -> tuple[str, list[sqlite3.Row]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        dataset = conn.execute(
            "SELECT id FROM datasets WHERE name=? LIMIT 1",
            (dataset_name,),
        ).fetchone()
        if dataset is None:
            raise SystemExit(f"dataset not found: {dataset_name}")
        rows = conn.execute(
            """
            SELECT file_name
            FROM documents
            WHERE dataset_id=? AND status=?
            ORDER BY file_size ASC, file_name ASC
            """,
            (dataset["id"], "PENDING"),
        ).fetchall()
    return str(dataset["id"]), rows


def load_pending_mail_texts(args: argparse.Namespace) -> list[str]:
    dataset_id, rows = _mail_dataset(Path(args.db), args.dataset)
    data_dir = Path(args.storage_dir) / dataset_id
    texts: list[str] = []
    for row in rows[: args.limit]:
        path = data_dir / str(row["file_name"])
        if not path.exists():
            continue
        profile = build_mail_vector_profile(path, source_dir=data_dir)
        texts.append(profile.message_embedding_text(include_attachment_text=False))
        for attachment in profile.attachments:
            texts.append(attachment.embedding_text(profile))
    return texts


def load_normative_chunk_texts(args: argparse.Namespace) -> list[str]:
    with sqlite3.connect(args.db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT lc.text
            FROM lexical_chunks lc
            LEFT JOIN datasets d ON d.id = lc.dataset_id
            WHERE COALESCE(d.name, '') LIKE ?
              AND COALESCE(d.name, '') != ?
              AND LENGTH(lc.text) >= ?
            ORDER BY LENGTH(lc.text) DESC, lc.id ASC
            LIMIT ?
            """,
            (args.dataset_like, args.exclude_dataset, args.min_chars, args.limit),
        ).fetchall()
    return [str(row["text"]) for row in rows]


def _token_length_stats(texts: list[str], tokenizer: Any, seq_len: int) -> dict[str, Any]:
    lengths = [len(ids) for ids in tokenizer(texts, padding=False, truncation=False)["input_ids"]]
    chars = np.asarray([len(text) for text in texts], dtype=np.float32)
    tokens = np.asarray(lengths, dtype=np.float32)
    return {
        "chars_mean": float(np.mean(chars)),
        "chars_max": int(np.max(chars)),
        "tokens_mean": float(np.mean(tokens)),
        "tokens_p50": float(np.percentile(tokens, 50)),
        "tokens_p95": float(np.percentile(tokens, 95)),
        "tokens_max": int(np.max(tokens)),
        "truncated_at_seq_len": int(np.sum(tokens > seq_len)),
        "truncated_pct": round(float(np.mean(tokens > seq_len) * 100.0), 2),
    }


def _encode_coreml_texts(
    texts: list[str],
    *,
    tokenizer: Any,
    mlmodel: Any,
    seq_len: int,
    batch_size: int,
) -> np.ndarray:
    vectors: list[np.ndarray] = []
    for start in range(0, len(texts), batch_size):
        batch_texts = texts[start : start + batch_size]
        real_size = len(batch_texts)
        if real_size < batch_size:
            batch_texts = batch_texts + [batch_texts[-1]] * (batch_size - real_size)
        tokens = tokenizer(
            batch_texts,
            padding="max_length",
            truncation=True,
            max_length=seq_len,
            return_tensors="np",
        )
        out = mlmodel.predict(
            {
                "input_ids": tokens["input_ids"].astype(np.int32),
                "attention_mask": tokens["attention_mask"].astype(np.int32),
            }
        )["embeddings"]
        vec = np.asarray(out, dtype=np.float32)
        vec = vec / np.linalg.norm(vec, axis=1, keepdims=True)
        vectors.append(vec[:real_size])
    return np.concatenate(vectors, axis=0)


def _bench_texts(args: argparse.Namespace, texts: list[str], *, label: str) -> dict[str, Any]:
    import coremltools as ct

    if not texts:
        raise SystemExit(f"no {label} texts found")

    st_model = SentenceTransformer(args.model_id, device=args.st_device)
    st_model.max_seq_length = args.seq_len
    st_model.encode(texts[:1], normalize_embeddings=True, show_progress_bar=False, batch_size=args.st_batch_size)
    started = time.perf_counter()
    st_vecs = st_model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        batch_size=args.st_batch_size,
    ).astype(np.float32)
    st_sec = time.perf_counter() - started

    mlmodel = ct.models.MLModel(args.coreml_model, compute_units=_compute_unit(args.compute_units))
    tokenizer = st_model.tokenizer

    _encode_coreml_texts(
        texts[: args.coreml_batch_size],
        tokenizer=tokenizer,
        mlmodel=mlmodel,
        seq_len=args.seq_len,
        batch_size=args.coreml_batch_size,
    )
    started = time.perf_counter()
    coreml_vecs = _encode_coreml_texts(
        texts,
        tokenizer=tokenizer,
        mlmodel=mlmodel,
        seq_len=args.seq_len,
        batch_size=args.coreml_batch_size,
    )
    coreml_sec = time.perf_counter() - started

    cos = np.sum(st_vecs * coreml_vecs, axis=1) / (
        np.linalg.norm(st_vecs, axis=1) * np.linalg.norm(coreml_vecs, axis=1)
    )

    return {
        "status": "benchmarked",
        "sample": label,
        "texts": len(texts),
        "model_id": args.model_id,
        "seq_len": args.seq_len,
        "token_stats": _token_length_stats(texts, tokenizer, args.seq_len),
        "sentence_transformers": {
            "device": args.st_device,
            "sec": round(st_sec, 3),
            "texts_per_sec": round(len(texts) / st_sec, 3),
            "batch_size": args.st_batch_size,
        },
        "coreml": {
            "model": args.coreml_model,
            "compute_units": args.compute_units,
            "sec": round(coreml_sec, 3),
            "texts_per_sec": round(len(texts) / coreml_sec, 3),
            "batch_size": args.coreml_batch_size,
        },
        "agreement": {
            "cosine_mean": float(np.mean(cos)),
            "cosine_min": float(np.min(cos)),
            "cosine_p05": float(np.percentile(cos, 5)),
        },
    }


def bench_mail(args: argparse.Namespace) -> dict[str, Any]:
    texts = load_pending_mail_texts(args)
    result = _bench_texts(args, texts, label=f"{args.dataset}:pending")
    result["dataset"] = args.dataset
    result["pending_file_limit"] = args.limit
    return result


def bench_chunks(args: argparse.Namespace) -> dict[str, Any]:
    texts = load_normative_chunk_texts(args)
    result = _bench_texts(args, texts, label=f"lexical_chunks:{args.dataset_like}")
    result["dataset_like"] = args.dataset_like
    result["exclude_dataset"] = args.exclude_dataset
    result["min_chars"] = args.min_chars
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Core ML embedding conversion and mail speed.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    convert = sub.add_parser("convert-e5", help="Convert BERT-like E5-small to a static Core ML package.")
    convert.add_argument("--model-id", default="intfloat/multilingual-e5-small")
    convert.add_argument("--output", default="artifacts/coreml/multilingual_e5_small_b1_s128_static.mlpackage")
    convert.add_argument("--seq-len", type=int, default=128)
    convert.add_argument("--batch-size", type=int, default=1)
    convert.set_defaults(func=convert_e5)

    qwen = sub.add_parser("convert-qwen", help="Convert Qwen3-Embedding with a static decoder wrapper.")
    qwen.add_argument("--model-id", default="Qwen/Qwen3-Embedding-0.6B")
    qwen.add_argument("--output", default="artifacts/coreml/qwen3_embedding_06b_b1_s64_static.mlpackage")
    qwen.add_argument("--seq-len", type=int, default=64)
    qwen.add_argument("--batch-size", type=int, default=1)
    qwen.add_argument("--trace-only", action="store_true")
    qwen.set_defaults(func=convert_qwen)

    bench = sub.add_parser("bench-mail", help="Benchmark pending MAIL_Index texts without writing to Qdrant.")
    bench.add_argument("--model-id", default="intfloat/multilingual-e5-small")
    bench.add_argument("--coreml-model", default="artifacts/coreml/multilingual_e5_small_b1_s128_static.mlpackage")
    bench.add_argument("--compute-units", choices=["all", "cpu_only", "cpu_and_gpu", "cpu_and_ne"], default="cpu_and_ne")
    bench.add_argument("--seq-len", type=int, default=128)
    bench.add_argument("--st-device", default="cpu")
    bench.add_argument("--st-batch-size", type=int, default=8)
    bench.add_argument("--coreml-batch-size", type=int, default=1)
    bench.add_argument("--db", default="data/les_meta_qwen.db")
    bench.add_argument("--storage-dir", default="storage/datasets")
    bench.add_argument("--dataset", default="MAIL_Index")
    bench.add_argument("--limit", type=int, default=25)
    bench.set_defaults(func=bench_mail)

    chunks = sub.add_parser("bench-chunks", help="Benchmark indexed normative chunk texts without Qdrant writes.")
    chunks.add_argument("--model-id", default="Qwen/Qwen3-Embedding-0.6B")
    chunks.add_argument("--coreml-model", default="artifacts/coreml/qwen3_embedding_06b_b1_s256_static.mlpackage")
    chunks.add_argument("--compute-units", choices=["all", "cpu_only", "cpu_and_gpu", "cpu_and_ne"], default="cpu_and_ne")
    chunks.add_argument("--seq-len", type=int, default=256)
    chunks.add_argument("--st-device", default="mps")
    chunks.add_argument("--st-batch-size", type=int, default=1)
    chunks.add_argument("--coreml-batch-size", type=int, default=1)
    chunks.add_argument("--db", default="data/les_meta_qwen.db")
    chunks.add_argument("--dataset-like", default="NTD_%")
    chunks.add_argument("--exclude-dataset", default="MAIL_Index")
    chunks.add_argument("--min-chars", type=int, default=900)
    chunks.add_argument("--limit", type=int, default=32)
    chunks.set_defaults(func=bench_chunks)

    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
