"""Ingestion QA — отчёт о качестве корпуса (Codex §10.4, §11).

Read-only скан Qdrant: считает по сэмплу чанков метрики качества контента, которые движок
лечить не должен (это задача курирования, не рантайма): битые таблицы (`<br>`-суп), языковой
шум (англ. Revit-доки), кросс-датасетные дубли (один content_hash в разных датасетах),
полноту метаданных, короткие/пустые чанки. Дедуп переезжает СЮДА с hot-path (Codex §10).

    uv run python -m tools.ingestion_quality_report                 # сэмпл 4000, MD в stdout
    uv run python -m tools.ingestion_quality_report --limit 0       # весь корпус
    uv run python -m tools.ingestion_quality_report --json out.json # + машинный отчёт

Чистые функции скоринга (тестируются без Qdrant) + фетч/агрегация. Ничего не пишет в Qdrant.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from typing import Any

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_CYR_RE = re.compile(r"[а-яё]", re.IGNORECASE)
_LAT_RE = re.compile(r"[a-z]", re.IGNORECASE)

# Метаданные, чьё отсутствие ломает функции (context-окна, цитирование).
_REQUIRED_META = ("dataset_id", "chunk_ord", "content_hash")


# ── чистые функции скоринга (юнит-тестируемы) ──────────────────────────────────────────

def language_ratio(text: str) -> float:
    """Доля кириллицы среди буквенных символов (0..1). <0.3 на длинном тексте → языковой шум."""
    cyr = len(_CYR_RE.findall(text))
    lat = len(_LAT_RE.findall(text))
    total = cyr + lat
    return (cyr / total) if total else 1.0


def br_noise(text: str) -> int:
    """Сколько `<br>`-тегов в чанке (маркер деградированной таблицы)."""
    return len(_BR_RE.findall(text))


def is_broken_table(text: str) -> bool:
    """Битая табличная разметка: тег-суп `<br>` ИЛИ «пайп-каша» (много `|` без структуры)."""
    return br_noise(text) >= 2 or text.count("|") >= 8


def is_language_noise(text: str) -> bool:
    """Длинный фрагмент с почти нулевой кириллицей → англ. шум (Revit-API и т.п.)."""
    return len(text) >= 120 and language_ratio(text) < 0.15


def metadata_completeness(payload: dict[str, Any]) -> float:
    """Доля обязательных метаполей, что заполнены (0..1)."""
    present = sum(1 for k in _REQUIRED_META if payload.get(k) not in (None, ""))
    return present / len(_REQUIRED_META)


# ── фетч из Qdrant (read-only) ─────────────────────────────────────────────────────────

def _qdrant_url() -> str:
    return os.getenv("QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")


def _collection() -> str:
    env = os.getenv("RAG_COLLECTION", "").strip()  # явный приоритет (дев vs рантайм коллекция)
    if env:
        return env
    try:
        from backend.rag_config import rag_collection_name
        return rag_collection_name()
    except Exception:
        return "les_rag_qwen3_06b"


def scroll_points(limit: int, *, batch: int = 500) -> list[dict[str, Any]]:
    """Сэмпл точек коллекции (payload без векторов). limit=0 → весь корпус."""
    import httpx

    url = f"{_qdrant_url()}/collections/{_collection()}/points/scroll"
    out: list[dict[str, Any]] = []
    offset = None
    with httpx.Client(timeout=60.0) as c:
        while True:
            body: dict[str, Any] = {"limit": batch, "with_payload": True, "with_vector": False}
            if offset is not None:
                body["offset"] = offset
            r = c.post(url, json=body)
            r.raise_for_status()
            res = r.json()["result"]
            out.extend(res["points"])
            offset = res.get("next_page_offset")
            if offset is None or (limit and len(out) >= limit):
                break
    return out[:limit] if limit else out


# ── агрегация ──────────────────────────────────────────────────────────────────────────

def build_report(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Сэмпл точек → агрегированный отчёт качества."""
    n = len(points)
    if not n:
        return {"sampled": 0}
    broken_tbl = lang_noise = short = incomplete_meta = 0
    per_dataset: Counter = Counter()
    per_doctype: Counter = Counter()
    hash_to_datasets: dict[str, set] = defaultdict(set)
    hash_count: Counter = Counter()
    meta_sum = 0.0

    for p in points:
        pl = p.get("payload", {}) or {}
        text = str(pl.get("text", "") or "")
        if is_broken_table(text):
            broken_tbl += 1
        if is_language_noise(text):
            lang_noise += 1
        if len(text) < 120:
            short += 1
        mc = metadata_completeness(pl)
        meta_sum += mc
        if mc < 1.0:
            incomplete_meta += 1
        per_dataset[str(pl.get("dataset_name") or pl.get("dataset_id") or "?")] += 1
        per_doctype[str(pl.get("doc_type") or "?")] += 1
        h = str(pl.get("content_hash") or "")
        if h:
            hash_count[h] += 1
            hash_to_datasets[h].add(str(pl.get("dataset_id") or "?"))

    # кросс-датасетные дубли: один content_hash в >1 датасете
    cross_dups = {h: sorted(ds) for h, ds in hash_to_datasets.items() if len(ds) > 1}
    dup_chunks = sum(c - 1 for c in hash_count.values() if c > 1)  # лишние копии

    def pct(x: int) -> float:
        return round(100 * x / n, 1)

    return {
        "sampled": n,
        "quality": {
            "broken_tables_pct": pct(broken_tbl),
            "language_noise_pct": pct(lang_noise),
            "short_chunks_pct": pct(short),
            "incomplete_metadata_pct": pct(incomplete_meta),
            "avg_metadata_completeness": round(meta_sum / n, 3),
        },
        "duplicates": {
            "duplicate_chunks_in_sample": dup_chunks,
            "duplicate_chunks_pct": pct(dup_chunks),
            "cross_dataset_clusters": len(cross_dups),
            "cross_dataset_examples": dict(list(cross_dups.items())[:5]),
        },
        "by_dataset": dict(per_dataset.most_common(12)),
        "by_doc_type": dict(per_doctype.most_common(8)),
    }


def render_md(rep: dict[str, Any]) -> str:
    if not rep.get("sampled"):
        return "# Ingestion QA\n\nПусто — нет точек."
    q, d = rep["quality"], rep["duplicates"]
    lines = [
        f"# Ingestion QA — {rep['sampled']} чанков (сэмпл)",
        "",
        "## Качество контента",
        f"- Битые таблицы (`<br>`/пайп-каша): **{q['broken_tables_pct']}%**",
        f"- Языковой шум (англ., низкая кириллица): **{q['language_noise_pct']}%**",
        f"- Короткие чанки (<120 симв): {q['short_chunks_pct']}%",
        f"- Неполные метаданные: {q['incomplete_metadata_pct']}% (средняя полнота {q['avg_metadata_completeness']})",
        "",
        "## Дубли",
        f"- Лишних копий в сэмпле: **{d['duplicate_chunks_pct']}%** ({d['duplicate_chunks_in_sample']} шт)",
        f"- Кросс-датасетных кластеров (один хэш в разных датасетах): **{d['cross_dataset_clusters']}**",
        "",
        "## По датасетам (топ)",
    ]
    for ds, c in rep["by_dataset"].items():
        lines.append(f"- {ds}: {c}")
    lines += ["", "## По типу документа"]
    for dt, c in rep["by_doc_type"].items():
        lines.append(f"- {dt}: {c}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingestion QA — отчёт качества корпуса (read-only)")
    ap.add_argument("--limit", type=int, default=4000, help="размер сэмпла (0 = весь корпус)")
    ap.add_argument("--json", type=str, default="", help="путь для машинного JSON-отчёта")
    args = ap.parse_args()

    points = scroll_points(args.limit)
    rep = build_report(points)
    if args.json:
        from pathlib import Path
        Path(args.json).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(render_md(rep))


if __name__ == "__main__":
    main()
