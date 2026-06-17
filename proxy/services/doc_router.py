"""ADR-12 стадия-1 (системная): LLM-роутер по каталогу документов + кэш.

Доказано (2026-06-17): поверхностный поиск (dense/sparse/BM25/семантика по карточке)
НЕ мостит «серверная → помещение ЭВМ → СП 486/485», т.к. слово «серверная» буквально
сидит в СП типов зданий (тюрьмы/суды), а управляющие нормы описывают её категорией.
Ручная карта категория→нормы не масштабируется. Системно (ADR-11: LLM = «мост/понимание»,
не арифметика): LLM читает компактный каталог документов (шифр + область применения) и сам
выбирает регулирующие шифры — затем стадия-2 ищет ТОЛЬКО в них. Решения КЭШИРУЮТСЯ →
карта строит себя из использования, доля LLM-вызовов → 0 (паттерн ADR-11 «пиши в кэш»).

Аддитивно: каталог/LLM/JSON не вышли → [] → вызывающий падает на плоский поиск.
"""
from __future__ import annotations
import json
import logging
import os
import re
import sqlite3
from typing import Any, Optional

logger = logging.getLogger(__name__)

# dataset_id -> {file_name: scope_card_text}
_CATALOG: dict[str, dict[str, str]] = {}
# нормализованный запрос -> [file_name] (самонаращиваемая карта)
_ROUTE_CACHE: dict[str, list[str]] = {}
_CACHE_LOADED = False
_CACHE_DB = os.getenv("RAG_META_DB_PATH", "data/les_meta_qwen.db")


def _load_cache() -> None:
    """Поднять самонаращиваемую карту с диска (переживает рестарт)."""
    global _CACHE_LOADED
    if _CACHE_LOADED:
        return
    _CACHE_LOADED = True
    try:
        with sqlite3.connect(_CACHE_DB, timeout=5) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS doc_router_cache "
                "(key TEXT PRIMARY KEY, docs TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            for key, docs in conn.execute("SELECT key, docs FROM doc_router_cache"):
                try:
                    _ROUTE_CACHE[key] = json.loads(docs)
                except Exception:  # noqa: BLE001
                    continue
        logger.info("[DOC_ROUTER] карта поднята с диска: %d записей", len(_ROUTE_CACHE))
    except Exception as exc:  # noqa: BLE001 — кэш best-effort, без него работаем
        logger.warning("[DOC_ROUTER] кэш с диска не поднялся: %s", exc)


def _persist(key: str, docs: list[str]) -> None:
    try:
        with sqlite3.connect(_CACHE_DB, timeout=5) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS doc_router_cache "
                "(key TEXT PRIMARY KEY, docs TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO doc_router_cache(key, docs) VALUES (?, ?)",
                (key, json.dumps(docs, ensure_ascii=False)),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DOC_ROUTER] персист кэша не вышел: %s", exc)
_SCOPE_HEADINGS = ("област", "примен", "назначен", "введен", "общие положени", "сфера", "1.1")
_MAX_DOCS = 7


def _norm_q(q: str) -> str:
    return " ".join(re.findall(r"[а-яёa-z0-9]+", (q or "").lower()))


async def _build_catalog(rag_backend, dataset_id: str) -> dict[str, str]:
    """Карточка документа = scope-чанк (раздел «Область применения», не chunk_ord=0)."""
    try:
        from qdrant_client import models as qm
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DOC_ROUTER] qdrant models нет: %s", exc)
        return {}
    client = getattr(rag_backend, "aclient", None)
    coll = getattr(rag_backend, "collection_name", None)
    if client is None or not coll:
        return {}
    flt = qm.Filter(must=[qm.FieldCondition(key="dataset_id", match=qm.MatchValue(value=dataset_id))])
    best: dict[str, tuple] = {}
    offset, pages = None, 0
    while pages < 200:
        pts, offset = await client.scroll(
            collection_name=coll, scroll_filter=flt, limit=512,
            with_payload=["file_name", "chunk_ord", "text", "section_heading"],
            with_vectors=False, offset=offset,
        )
        for p in pts:
            pl = p.payload or {}
            fn = pl.get("file_name")
            if not fn:
                continue
            head = (pl.get("section_heading") or "").lower()
            co = pl.get("chunk_ord")
            co = co if isinstance(co, int) else 10 ** 9
            prio = (0 if any(k in head for k in _SCOPE_HEADINGS) else 1, co)
            cur = best.get(fn)
            if cur is None or prio < cur[0]:
                best[fn] = (prio, " ".join((pl.get("text") or "").split())[:220])
        pages += 1
        if offset is None:
            break
    catalog = {fn: scope for fn, (_p, scope) in best.items()}
    logger.info("[DOC_ROUTER] каталог %s: %d документов", dataset_id, len(catalog))
    return catalog


def _shifr(file_name: str) -> str:
    return file_name.split("/")[-1].replace(".docx", "")


async def _llm_route(question: str, catalog: dict[str, str]) -> list[str]:
    """LLM выбирает регулирующие документы из каталога. Возврат — file_name из каталога."""
    try:
        import httpx
    except Exception:  # noqa: BLE001
        return []
    lines = [f"- {_shifr(fn)}: {scope}" for fn, scope in sorted(catalog.items())]
    prompt = (
        "Ты маршрутизатор нормативной базы. Ниже КАТАЛОГ документов (шифр: область применения).\n"
        "По ВОПРОСУ выбери ТОЛЬКО документы, реально регулирующие тему (объект может называться в нормах "
        "иначе — напр. серверная = помещение с ЭВМ/электронной техникой).\n"
        'Верни строго JSON {"шифры":["..."]} — 3-7 шифров ИЗ каталога, без пояснений.\n\n'
        "КАТАЛОГ:\n" + "\n".join(lines) + f"\n\nВОПРОС: {question}"
    )
    base = (os.getenv("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1")
    model = os.getenv("OPENAI_MODEL", "").strip()
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if model and key:
        url = base.rstrip("/") + "/chat/completions"
        headers = {"content-type": "application/json", "Authorization": "Bearer " + key}
    else:  # локальный fallback
        url = os.getenv("MLX_URL", "http://127.0.0.1:8080").rstrip("/") + "/v1/chat/completions"
        model = os.getenv("MLX_MODEL", "")
        headers = {"content-type": "application/json"}
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 300, "temperature": 0}
    try:
        async with httpx.AsyncClient(timeout=float(os.getenv("LES_ROUTER_TIMEOUT_SEC", "30"))) as cl:
            r = await cl.post(url, json=body, headers=headers)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DOC_ROUTER] LLM-роутер не ответил: %s", exc)
        return []
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return []
    try:
        shifry = json.loads(m.group(0)).get("шифры") or []
    except Exception:  # noqa: BLE001
        return []
    # Валидация: оставляем только шифры, реально присутствующие в каталоге (анти-галлюцинация)
    out: list[str] = []
    for s in shifry:
        s = str(s).strip()
        for fn in catalog:
            if s and s in _shifr(fn) and fn not in out:
                out.append(fn)
                break
    return out[:_MAX_DOCS]


async def route_documents(
    *, question: str, expanded_query: str, dataset_ids: Optional[list[str]],
    rag_backend: Any, top_n: int = 7, min_docs: int = 1,
) -> list[str]:
    """file_name документов-узлов для scope-поиска. [] → плоский fallback."""
    if not dataset_ids:
        return []
    _load_cache()
    key = "|".join(sorted(dataset_ids)) + "::" + _norm_q(question)
    if key in _ROUTE_CACHE:
        cached = _ROUTE_CACHE[key]
        logger.info("[DOC_ROUTER] cache-hit (%d узлов)", len(cached))
        return cached
    picked: list[str] = []
    for did in dataset_ids:
        try:
            if did not in _CATALOG:
                _CATALOG[did] = await _build_catalog(rag_backend, did)
            catalog = _CATALOG[did]
            if not catalog:
                continue
            docs = await _llm_route(question, catalog)
            picked.extend(d for d in docs if d not in picked)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DOC_ROUTER] класс %s: %s", did, exc)
            continue
    if len(picked) < min_docs:
        return []
    _ROUTE_CACHE[key] = picked
    _persist(key, picked)
    logger.info("[DOC_ROUTER] узлы (%d, LLM): %s", len(picked),
                ", ".join(_shifr(d)[:24] for d in picked))
    return picked


def reset_cache() -> None:
    _CATALOG.clear()
    _ROUTE_CACHE.clear()
