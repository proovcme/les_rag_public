"""BGE-M3 learned-sparse эмбеддер (W2.4) — lexical_weights без FlagEmbedding.

BGE-M3 даёт разреженный вектор «term_id → вес» через голову `sparse_linear`
поверх скрытых состояний (relu). Считаем напрямую через transformers+torch
(уже в зависимостях) — без FlagEmbedding. Используется reindex-скриптом и
ретривом для Qdrant-native гибрида (dense Qwen + sparse BGE-M3), ADR-3/W2.4.

Модель грузится лениво; устройство — MPS (Apple) при наличии, иначе CPU.
Веса BGE-M3 — в HF-кэше (скачаны с зеркала, см. SKILL «Reranker»/W2.4).
"""

from __future__ import annotations

import glob
import logging
import os
import threading

logger = logging.getLogger(__name__)

# Имя named sparse-вектора в Qdrant (общий контракт reindex ↔ retrieve).
SPARSE_VECTOR_NAME = "bge_m3_sparse"

_MODEL_DIR_GLOB = "~/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/*"
_lock = threading.Lock()
_state: dict = {"tok": None, "model": None, "sparse_linear": None, "device": None, "specials": None}


def _snapshot_dir() -> str:
    matches = glob.glob(os.path.expanduser(_MODEL_DIR_GLOB))
    if not matches:
        raise FileNotFoundError(
            "BGE-M3 не найден в HF-кэше. Скачай веса с зеркала (hf-mirror.com): "
            "pytorch_model.bin, sparse_linear.pt, sentencepiece.bpe.model."
        )
    return matches[0]


def _ensure_loaded() -> None:
    if _state["model"] is not None:
        return
    with _lock:
        if _state["model"] is not None:
            return
        os.environ.setdefault("HF_HUB_OFFLINE", "1")  # веса в кэше — в сеть не лезть
        import torch
        from transformers import AutoModel, AutoTokenizer

        snap = _snapshot_dir()
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        logger.info("[SPARSE] загрузка BGE-M3 (%s) на %s", snap, device)
        tok = AutoTokenizer.from_pretrained(snap)
        model = AutoModel.from_pretrained(snap).to(device).eval()
        sparse_linear = torch.nn.Linear(model.config.hidden_size, 1)
        sd = torch.load(os.path.join(snap, "sparse_linear.pt"), map_location="cpu")
        sparse_linear.load_state_dict(sd)
        sparse_linear = sparse_linear.to(device).eval()
        _state.update(
            tok=tok, model=model, sparse_linear=sparse_linear, device=device,
            specials=set(tok.all_special_ids),
        )


def encode_sparse(texts: list[str], *, batch_size: int = 16, max_length: int = 512) -> list[dict[int, float]]:
    """Список текстов → список разреженных векторов {token_id: weight} (max-pool по позициям)."""
    _ensure_loaded()
    import torch

    tok = _state["tok"]
    model = _state["model"]
    sparse_linear = _state["sparse_linear"]
    device = _state["device"]
    specials = _state["specials"]

    out: list[dict[int, float]] = []
    for start in range(0, len(texts), batch_size):
        batch = [t or "" for t in texts[start : start + batch_size]]
        enc = tok(batch, return_tensors="pt", truncation=True, max_length=max_length, padding=True)
        enc = {k: v.to(device) for k, v in enc.items()}
        with torch.no_grad():
            hidden = model(**enc).last_hidden_state
            weights = torch.relu(sparse_linear(hidden).squeeze(-1))  # (B, seq)
        ids = enc["input_ids"].cpu().tolist()
        mask = enc["attention_mask"].cpu().tolist()
        w = weights.cpu().tolist()
        for row_ids, row_mask, row_w in zip(ids, mask, w):
            vec: dict[int, float] = {}
            for tid, m, wt in zip(row_ids, row_mask, row_w):
                if not m or wt <= 0 or tid in specials:
                    continue
                if wt > vec.get(tid, 0.0):
                    vec[tid] = wt
            out.append(vec)
    return out


def encode_one(text: str) -> dict[int, float]:
    return encode_sparse([text])[0]
