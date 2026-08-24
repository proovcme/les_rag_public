#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pikabu Construction R&D prototype: sample → RAW → filter → trees → SFT/preference.

Does not train models. Does not mass-download shards. Streams JSONL.ZST from HF.
Requires ephemeral: uv run --with zstandard --with requests python tools/pikabu_construction_rd.py
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# Windows-safe UTF-8 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HF_REPO = "IlyaGusev/pikabu"
DEFAULT_SHARD = "00.jsonl.zst"

# Strong tags (alone enough to enter candidate pool).
CONSTRUCTION_TAGS_STRONG = {
    "строительство",
    "ремонт",
    "архитектура",
    "сантехника",
    "электрика",
    "отопление",
    "вентиляция",
    "кондиционирование",
    "кровля",
    "фундамент",
    "бетон",
    "стройка",
    "прораб",
    "жкх",
    "bim",
    "cad",
}
# Weak tags need keyword corroboration.
CONSTRUCTION_TAGS_WEAK = {
    "своими руками",
    "дизайн интерьера",
    "недвижимость",
    "дача",
    "дом",
    "квартира",
    "смета",
}
CONSTRUCTION_TAGS = CONSTRUCTION_TAGS_STRONG | CONSTRUCTION_TAGS_WEAK

# Keyword / BM25-ish tokens (title + body + tags).
CONSTRUCTION_KEYWORDS = [
    r"строительств",
    r"капремонт",
    r"ремонт\s+(квартир|дом|ванн|санузл|кровл|фасад)",
    r"архитектур",
    r"\bbim\b",
    r"\bcad\b",
    r"revit",
    r"фундамент",
    r"железобетон",
    r"\bбетон",
    r"металлоконструк",
    r"кладк",
    r"фасад",
    r"кровл",
    r"стропил",
    r"отделк",
    r"электромонтаж",
    r"электропровод",
    r"\bэом\b",
    r"слаботоч",
    r"вентиляц",
    r"отоплени",
    r"кондиционер",
    r"сантехник",
    r"канализац",
    r"водоснаб",
    r"пожарн(ая|ой|ые)\s+систем",
    r"дымоудален",
    r"лифт(ы|ов|а)?\b",
    r"стройматериал",
    r"прораб",
    r"подрядчик",
    r"смет(а|ы|н)",
    r"\bснип\b",
    r"\bгост\b",
    r"\bсп\s?\d",
    r"гэсн",
    r"фснб",
    r"гидроизоляц",
    r"теплоизоляц",
    r"стяжк",
    r"штукатур",
    r"гипсокартон",
    r"утеплит",
    r"обследован(ие|ия)\s+(здан|строен)",
]

CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("HVAC", [r"вентиляц", r"отоплени", r"кондиционер", r"\bов\b", r"теплоснаб"]),
    ("VK", [r"сантехник", r"канализац", r"водоснаб", r"\bвк\b", r"унитаз", r"смесител"]),
    ("EOM", [r"электри", r"\bэом\b", r"проводк", r"щит\b", r"автомат\b", r"слаботоч"]),
    ("KR", [r"фундамент", r"бетон", r"железобетон", r"металлоконструк", r"кладк", r"перекрыт"]),
    ("AR", [r"архитектур", r"фасад", r"планировк", r"дизайн интерьера"]),
    ("ROOF", [r"кровл", r"стропил", r"черепиц", r"гидроизоляц"]),
    ("FINISH", [r"отделк", r"штукатур", r"гипсокартон", r"стяжк", r"плитк"]),
    ("FIRE", [r"пожарн", r"дымоудален", r"огнезащит"]),
    ("BIM", [r"\bbim\b", r"\bcad\b", r"revit", r"автокад"]),
    ("NORM", [r"\bснип\b", r"\bгост\b", r"\bсп\s?\d", r"гэсн", r"фснб", r"смет"]),
    ("SITE", [r"прораб", r"подрядчик", r"стройплощад", r"организац.*строител"]),
    ("DIY", [r"своими руками", r"ремонт квартир", r"дача"]),
]

POLITICS_RE = re.compile(r"политик|выбор|путин|навальн|госдум|митинг", re.I)
NEWS_RE = re.compile(r"новост|срочно|происшеств", re.I)
NSFW_RE = re.compile(r"nsfw|18\+|эротик|секс", re.I)
VIOLENCE_RE = re.compile(r"убийств|кров(ь|и)\b|расстрел", re.I)
HUMOR_RE = re.compile(r"юмор|смешн|прикол", re.I)
NORMATIVE_RE = re.compile(r"снип|гост|\bсп\s?\d|гэсн|фснб|норматив", re.I)

KEYWORD_RES = [re.compile(p, re.I) for p in CONSTRUCTION_KEYWORDS]


def anon_author(author_id: Any) -> str:
    raw = str(author_id if author_id is not None else "unknown")
    return "a_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def flatten_comments(comments: Any) -> list[dict[str, Any]]:
    if not comments:
        return []
    if isinstance(comments, list):
        return [c for c in comments if isinstance(c, dict)]
    if isinstance(comments, dict) and "id" in comments:
        keys = list(comments.keys())
        n = len(comments.get("id") or [])
        out = []
        for i in range(n):
            item = {}
            for k in keys:
                vals = comments.get(k) or []
                item[k] = vals[i] if i < len(vals) else None
            out.append(item)
        return out
    return []


def post_blob(post: dict[str, Any]) -> str:
    tags = " ".join(post.get("tags") or [])
    return "\n".join(
        [
            str(post.get("title") or ""),
            str(post.get("text_markdown") or ""),
            tags,
        ]
    )


def tag_hit(post: dict[str, Any]) -> tuple[list[str], list[str]]:
    tags = [str(t).strip().lower() for t in (post.get("tags") or [])]
    strong, weak = [], []
    for t in tags:
        if t in CONSTRUCTION_TAGS_STRONG or any(ct in t for ct in CONSTRUCTION_TAGS_STRONG):
            strong.append(t)
        elif t in CONSTRUCTION_TAGS_WEAK or any(ct in t for ct in CONSTRUCTION_TAGS_WEAK):
            weak.append(t)
    return strong, weak


def keyword_hits(text: str) -> list[str]:
    hits = []
    for rx in KEYWORD_RES:
        if rx.search(text):
            hits.append(rx.pattern)
    return hits


def is_construction_candidate(
    strong_tags: list[str], weak_tags: list[str], kws: list[str], comment_kws: list[str]
) -> bool:
    """Stricter gate: avoid 'дача/квартира' alone and single weak keyword hits."""
    if strong_tags:
        return True
    # Weak tag + at least one construction keyword in post/comments
    if weak_tags and (kws or comment_kws):
        return True
    # At least two distinct keyword patterns in post body/title, or one + comment tech
    if len(kws) >= 2:
        return True
    if kws and comment_kws:
        return True
    # Single strong professional keyword patterns
    strong_kw = {
        r"строительств",
        r"фундамент",
        r"железобетон",
        r"вентиляц",
        r"канализац",
        r"\bснип\b",
        r"\bгост\b",
        r"гэсн",
        r"фснб",
        r"\bbim\b",
        r"металлоконструк",
        r"гидроизоляц",
    }
    if any(k in strong_kw for k in kws):
        return True
    return False


def assign_categories(text: str) -> list[str]:
    cats = []
    for name, patterns in CATEGORY_RULES:
        for p in patterns:
            if re.search(p, text, re.I):
                cats.append(name)
                break
    return cats or ["GENERAL_CONSTRUCTION"]


def heuristic_class(post: dict[str, Any], comments: list[dict[str, Any]]) -> tuple[int, str]:
    """0..4 construction class + reason. Prototype heuristic, not LLM."""
    text = post_blob(post)
    strong_tags, weak_tags = tag_hit(post)
    tags = strong_tags + weak_tags
    kws = keyword_hits(text)
    long_tech_comments = 0
    for c in comments:
        body = str(c.get("text_markdown") or "")
        if len(body) >= 200 and keyword_hits(body):
            long_tech_comments += 1

    if not tags and not kws and long_tech_comments == 0:
        return 0, "no_signal"

    professional_markers = sum(
        1
        for p in [
            r"\bснип\b",
            r"\bгост\b",
            r"\bbim\b",
            r"проектн",
            r"рабоч(ие|их)\s+чертеж",
            r"спецификац",
            r"инженерн",
            r"гэсн",
            r"фснб",
        ]
        if re.search(p, text, re.I)
    )
    diy_markers = sum(
        1
        for p in [r"своими руками", r"как сделать", r"подскажите", r"квартир", r"дач"]
        if re.search(p, text, re.I)
    )

    if professional_markers >= 2 or any("bim" in t for t in tags) or long_tech_comments >= 3:
        return 4, "professional_markers"
    if strong_tags or (
        kws and (len(str(post.get("text_markdown") or "")) > 400 or long_tech_comments >= 1)
    ):
        if diy_markers and professional_markers == 0 and long_tech_comments <= 1 and not strong_tags:
            return 2, "diy_repair"
        return 3, "construction_case"
    if weak_tags or kws or long_tech_comments:
        return 1, "indirect_mention"
    return 0, "no_signal"


def content_flags(text: str, tags: list[str]) -> dict[str, bool]:
    blob = text + " " + " ".join(tags)
    return {
        "politics": bool(POLITICS_RE.search(blob)),
        "news": bool(NEWS_RE.search(blob)),
        "nsfw": bool(NSFW_RE.search(blob)),
        "violence": bool(VIOLENCE_RE.search(blob)),
        "humor": bool(HUMOR_RE.search(blob)),
        "normative": bool(NORMATIVE_RE.search(blob)),
    }


def build_comment_tree(comments: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach depth/level; return nodes + stats."""
    by_id: dict[int, dict[str, Any]] = {}
    children: dict[int, list[int]] = defaultdict(list)
    for c in comments:
        try:
            cid = int(c["id"])
        except (TypeError, ValueError, KeyError):
            continue
        parent = int(c.get("parent_id") or 0)
        node = {
            "id": cid,
            "parent_id": parent,
            "text": str(c.get("text_markdown") or "").strip(),
            "rating": int(c.get("rating") or 0),
            "pluses": int(c.get("pluses") or 0),
            "minuses": int(c.get("minuses") or 0),
            "timestamp": c.get("timestamp"),
            "author_hash": anon_author(c.get("author_id")),
            "level": 0,
        }
        by_id[cid] = node
        children[parent].append(cid)

    def walk(cid: int, level: int) -> None:
        node = by_id.get(cid)
        if not node:
            return
        node["level"] = level
        for child in children.get(cid, []):
            walk(child, level + 1)

    roots = children.get(0, [])
    for rid in roots:
        walk(rid, 0)

    # Orphans (parent missing): treat as roots
    orphan = 0
    for cid, node in by_id.items():
        if node["parent_id"] and node["parent_id"] not in by_id and node["parent_id"] != 0:
            orphan += 1
            if node["level"] == 0 and cid not in roots:
                node["level"] = 0

    max_depth = max((n["level"] for n in by_id.values()), default=-1) + 1 if by_id else 0
    with_children = sum(1 for cid in by_id if children.get(cid))
    stats = {
        "n_comments": len(by_id),
        "n_roots": len(roots),
        "n_orphans": orphan,
        "max_depth": max_depth,
        "n_nodes_with_children": with_children,
        "tree_ok": orphan == 0 and (len(by_id) == 0 or len(roots) > 0 or len(by_id) == 0),
    }
    return list(by_id.values()), stats


def period_bucket(ts: Any) -> str:
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"
    except Exception:
        return "unknown"


def normalize_score_in_post(score: int, siblings: list[int]) -> float:
    if not siblings:
        return 0.0
    mean = sum(siblings) / len(siblings)
    var = sum((x - mean) ** 2 for x in siblings) / max(len(siblings), 1)
    std = math.sqrt(var) or 1.0
    return (score - mean) / std


def stream_shard(shard: str, max_posts: int, timeout: int = 120) -> Iterator[dict[str, Any]]:
    import requests
    import zstandard as zstd
    from huggingface_hub import hf_hub_url

    url = hf_hub_url(repo_id=HF_REPO, filename=shard, repo_type="dataset")
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        dctx = zstd.ZstdDecompressor()
        with dctx.stream_reader(r.raw) as reader:
            text = io.TextIOWrapper(reader, encoding="utf-8")
            for i, line in enumerate(text):
                if i >= max_posts:
                    break
                yield json.loads(line)


def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE posts_raw (
          post_id INTEGER PRIMARY KEY,
          title TEXT,
          text_markdown TEXT,
          timestamp INTEGER,
          rating INTEGER,
          pluses INTEGER,
          minuses INTEGER,
          url TEXT,
          tags_json TEXT,
          author_hash TEXT,
          period TEXT,
          source_shard TEXT,
          raw_json TEXT
        );
        CREATE TABLE comments_raw (
          comment_id INTEGER PRIMARY KEY,
          post_id INTEGER,
          parent_id INTEGER,
          text_markdown TEXT,
          timestamp INTEGER,
          rating INTEGER,
          pluses INTEGER,
          minuses INTEGER,
          author_hash TEXT,
          FOREIGN KEY(post_id) REFERENCES posts_raw(post_id)
        );
        CREATE TABLE posts_classified (
          post_id INTEGER PRIMARY KEY,
          construction_class INTEGER,
          class_reason TEXT,
          categories_json TEXT,
          flags_json TEXT,
          tag_hits_json TEXT,
          keyword_hits_json TEXT,
          tree_stats_json TEXT
        );
        """
    )
    return conn


def make_sft_pairs(post: dict[str, Any], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {n["id"]: n for n in nodes}
    children = defaultdict(list)
    for n in nodes:
        children[n["parent_id"]].append(n)

    pairs = []
    # Prefer reply chains where child is substantive and well-rated vs siblings.
    for parent_id, kids in children.items():
        if parent_id == 0:
            context = f"Пост: {post.get('title')}\n\n{post.get('text_markdown') or ''}".strip()
        else:
            parent = by_id.get(parent_id)
            if not parent:
                continue
            context = (
                f"Пост: {post.get('title')}\n\n"
                f"Комментарий (контекст):\n{parent['text']}"
            ).strip()
        strong = [k for k in kids if len(k["text"]) >= 80]
        if not strong:
            continue
        strong.sort(key=lambda x: x["rating"], reverse=True)
        best = strong[0]
        if best["rating"] < 1 and len(best["text"]) < 200:
            continue
        pairs.append(
            {
                "messages": [
                    {"role": "user", "content": context[:4000]},
                    {"role": "assistant", "content": best["text"][:4000]},
                ],
                "metadata": {
                    "post_id": post["id"],
                    "comment_id": best["id"],
                    "parent_id": parent_id,
                    "score": best["rating"],
                    "category": (post.get("_categories") or ["GENERAL_CONSTRUCTION"])[0],
                    "construction_class": post.get("_class"),
                    "period": period_bucket(post.get("timestamp")),
                },
            }
        )
    return pairs[:5]


def make_preference_pairs(post: dict[str, Any], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    children = defaultdict(list)
    by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        children[n["parent_id"]].append(n)

    out = []
    for parent_id, kids in children.items():
        comparable = [k for k in kids if len(k["text"]) >= 60]
        if len(comparable) < 2:
            continue
        scores = [k["rating"] for k in comparable]
        comparable.sort(key=lambda x: x["rating"], reverse=True)
        chosen, rejected = comparable[0], comparable[-1]
        # Guard against false preference: require clear gap + similar length band
        if chosen["rating"] - rejected["rating"] < 5:
            continue
        len_ratio = len(chosen["text"]) / max(len(rejected["text"]), 1)
        if len_ratio < 0.35 or len_ratio > 3.0:
            continue
        if parent_id == 0:
            prompt = f"Пост: {post.get('title')}\n\n{post.get('text_markdown') or ''}".strip()
        else:
            parent = by_id.get(parent_id)
            if not parent:
                continue
            prompt = f"Пост: {post.get('title')}\n\nКонтекст:\n{parent['text']}".strip()
        out.append(
            {
                "prompt": prompt[:4000],
                "chosen": chosen["text"][:4000],
                "rejected": rejected["text"][:4000],
                "metadata": {
                    "post_id": post["id"],
                    "parent_id": parent_id,
                    "chosen_score": chosen["rating"],
                    "rejected_score": rejected["rating"],
                    "chosen_norm": round(normalize_score_in_post(chosen["rating"], scores), 3),
                    "rejected_norm": round(normalize_score_in_post(rejected["rating"], scores), 3),
                    "period": period_bucket(post.get("timestamp")),
                    "category": (post.get("_categories") or ["GENERAL_CONSTRUCTION"])[0],
                },
            }
        )
    return out[:5]


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "raw" / "pikabu_sample.sqlite"
    conn = init_db(db_path)

    scanned = 0
    candidates = 0
    class_hist: Counter[int] = Counter()
    cat_hist: Counter[str] = Counter()
    period_hist: Counter[str] = Counter()
    tree_ok = 0
    tree_total = 0
    sft_rows: list[dict[str, Any]] = []
    pref_rows: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []

    print(f"Streaming up to {args.max_posts} posts from {args.shard} ...", flush=True)
    for post in stream_shard(args.shard, args.max_posts):
        scanned += 1
        comments = flatten_comments(post.get("comments"))
        text = post_blob(post)
        strong_tags, weak_tags = tag_hit(post)
        tags = strong_tags + weak_tags
        kws = keyword_hits(text)
        comment_kws: list[str] = []
        for c in comments[:40]:
            comment_kws.extend(keyword_hits(str(c.get("text_markdown") or "")))
        comment_kws = list(dict.fromkeys(comment_kws))
        kws = list(dict.fromkeys(kws))

        if not is_construction_candidate(strong_tags, weak_tags, kws, comment_kws):
            continue

        candidates += 1
        cls, reason = heuristic_class(post, comments)
        cats = assign_categories(text)
        flags = content_flags(text, post.get("tags") or [])
        flags["construction"] = cls >= 1
        flags["professional_construction"] = cls >= 4

        nodes, tree_stats = build_comment_tree(comments)
        tree_total += 1
        if tree_stats["n_orphans"] == 0:
            tree_ok += 1

        author_hash = anon_author(post.get("author_id"))
        period = period_bucket(post.get("timestamp"))
        period_hist[period] += 1
        class_hist[cls] += 1
        for c in cats:
            cat_hist[c] += 1

        # RAW store (immutable for this prototype run; flags live in classified)
        conn.execute(
            """INSERT OR REPLACE INTO posts_raw VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(post["id"]),
                post.get("title"),
                post.get("text_markdown"),
                int(post.get("timestamp") or 0),
                int(post.get("rating") or 0),
                int(post.get("pluses") or 0),
                int(post.get("minuses") or 0),
                post.get("url"),
                json.dumps(post.get("tags") or [], ensure_ascii=False),
                author_hash,
                period,
                args.shard,
                json.dumps(
                    {
                        "id": post.get("id"),
                        "title": post.get("title"),
                        "text_markdown": post.get("text_markdown"),
                        "timestamp": post.get("timestamp"),
                        "rating": post.get("rating"),
                        "pluses": post.get("pluses"),
                        "minuses": post.get("minuses"),
                        "url": post.get("url"),
                        "tags": post.get("tags"),
                        "author_id": None,  # stripped in stored raw snapshot
                        "username": None,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        for n in nodes:
            conn.execute(
                """INSERT OR REPLACE INTO comments_raw VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    n["id"],
                    int(post["id"]),
                    n["parent_id"],
                    n["text"],
                    int(n["timestamp"] or 0),
                    n["rating"],
                    n["pluses"],
                    n["minuses"],
                    n["author_hash"],
                ),
            )
        conn.execute(
            """INSERT OR REPLACE INTO posts_classified VALUES (?,?,?,?,?,?,?,?)""",
            (
                int(post["id"]),
                cls,
                reason,
                json.dumps(cats, ensure_ascii=False),
                json.dumps(flags, ensure_ascii=False),
                json.dumps(tags, ensure_ascii=False),
                json.dumps(kws[:20], ensure_ascii=False),
                json.dumps(tree_stats, ensure_ascii=False),
            ),
        )

        post["_class"] = cls
        post["_categories"] = cats
        if cls >= 2:
            sft_rows.extend(make_sft_pairs(post, nodes))
            pref_rows.extend(make_preference_pairs(post, nodes))
        if cls >= 2 and len(examples) < 5:
            top_comments = sorted(nodes, key=lambda x: x["rating"], reverse=True)[:3]
            examples.append(
                {
                    "post_id": post["id"],
                    "title": post.get("title"),
                    "class": cls,
                    "categories": cats,
                    "rating": post.get("rating"),
                    "n_comments": len(nodes),
                    "tree_stats": tree_stats,
                    "sample_comments": [
                        {
                            "id": c["id"],
                            "parent_id": c["parent_id"],
                            "level": c["level"],
                            "rating": c["rating"],
                            "author_hash": c["author_hash"],
                            "text_preview": (c["text"][:240] + ("…" if len(c["text"]) > 240 else "")),
                        }
                        for c in top_comments
                    ],
                }
            )

        if scanned % 500 == 0:
            conn.commit()
            print(
                f"  scanned={scanned} candidates={candidates} "
                f"sft={len(sft_rows)} pref={len(pref_rows)}",
                flush=True,
            )

    conn.commit()
    conn.close()

    dataset_dir = out_dir / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    sft_path = dataset_dir / "sft_sample.jsonl"
    pref_path = dataset_dir / "preference_sample.jsonl"
    with sft_path.open("w", encoding="utf-8") as f:
        for row in sft_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with pref_path.open("w", encoding="utf-8") as f:
        for row in pref_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Extrapolate rough corpus size from sample hit-rate
    hit_rate = candidates / scanned if scanned else 0.0
    strong_rate = sum(class_hist[c] for c in (2, 3, 4)) / scanned if scanned else 0.0
    total_posts = 6_907_622
    estimate = {
        "sample_scanned": scanned,
        "sample_candidates_any_signal": candidates,
        "sample_class_2_plus": sum(class_hist[c] for c in (2, 3, 4)),
        "hit_rate_any": round(hit_rate, 5),
        "hit_rate_class_2_plus": round(strong_rate, 5),
        "extrapolated_any_signal_posts": int(total_posts * hit_rate),
        "extrapolated_class_2_plus_posts": int(total_posts * strong_rate),
        "note": "Extrapolation from one shard prefix; tag distribution may drift across eras.",
    }

    report = {
        "source_primary": {
            "id": "IlyaGusev/pikabu",
            "alive": True,
            "posts": 6_907_622,
            "download_size_bytes": 20_196_853_689,
            "streaming": True,
            "has_parent_id": True,
            "period_approx": "historical pikastat dump (pre-2021 bulk; HF card 2023)",
            "license_note": "Loader Apache-2.0; content is scraped Pikabu UGC (not a clean ML license); PII present",
        },
        "prototype": {
            "shard": args.shard,
            "scanned": scanned,
            "candidates": candidates,
            "class_histogram": {str(k): v for k, v in sorted(class_hist.items())},
            "category_histogram": dict(cat_hist.most_common()),
            "period_histogram": dict(period_hist.most_common()),
            "tree_ok_ratio": round(tree_ok / tree_total, 4) if tree_total else None,
            "sft_rows": len(sft_rows),
            "preference_rows": len(pref_rows),
            "db": str(db_path),
            "sft_path": str(sft_path),
            "pref_path": str(pref_path),
        },
        "estimate": estimate,
        "examples": examples,
        "pipeline": "SOURCE(HF stream) → RAW(sqlite) → CLASSIFIED(flags+class) → DATASET(jsonl)",
        "next_step": [
            "Scan more shards / full stream for tag frequencies",
            "Manual label ~100 candidates to calibrate LLM classifier",
            "Do NOT mix FSNB into LoRA weights; keep norms in RAG/tools",
            "Optional incremental collector only for post-dump freshness",
        ],
    }
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["prototype"], ensure_ascii=False, indent=2))
    print(json.dumps(report["estimate"], ensure_ascii=False, indent=2))
    print(f"Wrote {report_path}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--max-posts", type=int, default=3000)
    p.add_argument("--shard", default=DEFAULT_SHARD)
    p.add_argument("--out-dir", default="storage/pikabu_rd")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
