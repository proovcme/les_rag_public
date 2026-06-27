#!/usr/bin/env python
"""v0.15 — сэмпл РЕАЛЬНЫХ терминов/заголовков из sidecar-извлечений (для позитивного smoke).

Читает _extracted/ датасета, достаёт кандидаты: норм-коды (ГОСТ/СП/СНиП NNN), частые содержательные
слова, заголовки (para0). Чтобы smoke искал не только заведомо-отсутствующее, а реально присутствующее.

  python scripts/sample_extracted_terms_v15.py --dataset-id <ID> \
    --storage-root /Users/ovc/LES/storage/datasets --top-n 20 --output artifacts/terms.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from proxy.services import doc_extract_service as de

_NORM_RE = re.compile(r"\b(?:ГОСТ|СП|СНиП)\s?[\dR.\-]+", re.I)
_WORD_RE = re.compile(r"\b[А-Яа-яЁё]{6,}\b")
_STOP = {"который", "которые", "которых", "настоящий", "настоящего", "следующих", "должны",
         "должен", "соответствии", "требования", "межгосударственный"}


def sample(dataset_id: str, *, storage_root: Path, top_n: int) -> dict:
    items = de.read_sidecars(storage_root, dataset_id)
    norm_codes: Counter = Counter()
    words: Counter = Counter()
    headings = []
    for it in items:
        txt = str(it.get("text", ""))
        for m in _NORM_RE.findall(txt):
            norm_codes[m.strip()] += 1
        for w in _WORD_RE.findall(txt.lower()):
            if w not in _STOP:
                words[w] += 1
        if it.get("paragraph_index") == 0 and txt.strip():
            headings.append({"file": it.get("original_file_name"), "heading": txt[:80],
                             "source_ref": it.get("source_ref")})
    # кандидаты с примером source_ref
    from proxy.services.source_adapters import _norm

    def _first_ref(term):
        tn = _norm(term)
        for it in items:
            if tn and tn in _norm(str(it.get("text", ""))):
                return {"file": it.get("original_file_name"), "source_ref": it.get("source_ref"),
                        "snippet": str(it.get("text", ""))[:120]}
        return None

    top_words = [w for w, _ in words.most_common(top_n)]
    top_norms = [n for n, _ in norm_codes.most_common(min(10, top_n))]
    candidates = []
    for t in (top_norms[:5] + top_words[:8]):
        ref = _first_ref(t)
        if ref:
            candidates.append({"term": t, **ref})
    return {"dataset_id": dataset_id, "sidecar_items": len(items), "top_norm_codes": top_norms,
            "top_words": top_words, "headings": headings[:10], "candidates": candidates[:top_n]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-id", required=True)
    ap.add_argument("--storage-root", default="storage/datasets")
    ap.add_argument("--top-n", type=int, default=20)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()
    rep = sample(args.dataset_id, storage_root=Path(args.storage_root), top_n=args.top_n)
    print(f"# sample terms | dataset={args.dataset_id} | sidecar_items={rep['sidecar_items']}")
    print(f"  норм-коды: {rep['top_norm_codes'][:6]}")
    print(f"  слова:     {rep['top_words'][:8]}")
    print(f"  кандидатов с source_ref: {len(rep['candidates'])}")
    for c in rep["candidates"][:6]:
        print(f"    «{c['term']}» → {str(c['file'])[:36]} {c['source_ref'].split('#')[-1]}")
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
        print(f"\nОтчёт: {out}")


if __name__ == "__main__":
    main()
