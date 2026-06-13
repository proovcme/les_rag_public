"""BM25/IDF sparse-вектора для Qdrant-native гибрида (W2.4).

Вместо нейросетевого BGE-M3 (на этом железе ~9 ч на 169k) — лёгкий лексический
sparse: токены → стем → TF. IDF Qdrant считает САМ по статистике коллекции
(`SparseVectorParams(modifier=Idf)`), поэтому корпусный проход не нужен — индексация
за минуты, ноль нагрузки на Metal. Токенизация/стемминг переиспользуют тот же код,
что самописный FTS (`lexical_index_service`) — выдача консистентна с гибридом.

Term id = детерминированный crc32 стема (uint31). Коллизии редки в 2^31.
"""

from __future__ import annotations

import re
import zlib
from collections import Counter

from proxy.services.lexical_index_service import NO_STEM_WORDS, TOKEN_RE, stem_russian_word

# Имя named sparse-вектора в Qdrant (общий контракт reindex ↔ retrieve).
SPARSE_VECTOR_NAME = "bm25_sparse"

_DIGIT_RE = re.compile(r"\d")


def _term_id(stem: str) -> int:
    return zlib.crc32(stem.encode("utf-8")) & 0x7FFFFFFF


def tokenize(text: str) -> list[str]:
    """Текст → список стемов (как в FTS: casefold, ё→е, стоп-слова, стемминг ≥4)."""
    out: list[str] = []
    for raw in TOKEN_RE.findall((text or "").casefold().replace("ё", "е")):
        token = raw.strip(".-")
        if len(token) < 3 or token in NO_STEM_WORDS:
            continue
        # числа/шифры (СП, ГОСТ, 4.13130) оставляем как есть — точное совпадение важно
        if _DIGIT_RE.search(token):
            out.append(token)
            continue
        stem = stem_russian_word(token) if len(token) >= 4 else token
        if len(stem) >= 3 and stem.isalpha():
            out.append(stem)
        else:
            out.append(token)
    return out


def encode_bm25(text: str) -> dict[int, float]:
    """Текст → {term_id: term_frequency}. IDF применит Qdrant (modifier=Idf)."""
    counts = Counter(_term_id(tok) for tok in tokenize(text))
    return {tid: float(tf) for tid, tf in counts.items()}
