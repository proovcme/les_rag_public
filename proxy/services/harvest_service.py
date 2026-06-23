"""Harvest-петля: verify-правки оператора → train-set + таксономия ошибок.

verify = разметка (см. verify_service): каждая подтверждённая/исправленная таблица —
ground truth (картинка страницы + target-строки), а с захватом pred_rows ещё и
размеченный дифф «модель дала → оператор исправил».

Эта петля:
  1. build_training_set — собирает базонезависимый датасет (картинка → target) из всех
     verify-записей. Это ДОЛГОВЕЧНЫЙ актив: на нём гоняется бенч и (если дойдём) учится
     LoRA на любой новой базовой VL-модели.
  2. error_taxonomy — на парах pred→target раскладывает ошибки по классам (путаница
     цифр/латиница-кириллица, потерянные строки/колонки, числовые расхождения), чтобы
     ВИДЕТЬ: systematic ли косяк (→ есть смысл в LoRA) или шум.

0 LLM. Источник данных — verify_service.VERIFY_DIR / CACHE_DIR (берутся в рантайме,
чтобы тесты могли подменить каталоги).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Optional

from proxy.services import verify_service

POSITIVE_VERDICTS = {"ok", "corrected"}  # rejected — не образец таблицы, в train не берём

DEFAULT_OUT = Path("data/train")

# Часто путаемые при распознавании пары (в обе стороны): цифры↔буквы и латиница↔кириллица.
_CONFUSABLES = {
    "0": "OoОо", "1": "lI|", "3": "ЗзEе", "5": "SsБб", "6": "бG", "8": "ВB",
    "9": "gq", "O": "0Оо", "S": "5", "B": "8В", "З": "3", "о": "0Oo",
    "а": "a", "е": "e3", "о": "o0", "р": "p", "с": "c", "у": "y", "х": "x",
    "a": "а", "e": "ео", "o": "о", "p": "р", "c": "с", "y": "у", "x": "х",
}


def _records() -> Iterator[dict[str, Any]]:
    d = verify_service.VERIFY_DIR
    if not d.exists():
        return
    for f in sorted(d.glob("*.json")):
        try:
            yield json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue


def _columns(rows: list[dict] | None) -> list[str]:
    cols: list[str] = []
    for r in rows or []:
        if isinstance(r, dict):
            for k in r:
                if k not in cols:
                    cols.append(k)
    return cols


# ── 1. train-set ────────────────────────────────────────────────────────────

def build_training_set(out_dir: str | Path = DEFAULT_OUT) -> dict[str, Any]:
    """Собрать датасет (картинка → target-строки) из verify-записей. Возвращает manifest."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ds_path = out_dir / "dataset.jsonl"

    n = 0
    by_verdict: dict[str, int] = {}
    with_image = with_pred = rows_total = 0
    with ds_path.open("w", encoding="utf-8") as fh:
        for rec in _records():
            verdict = str(rec.get("verdict") or "ok")
            by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
            if verdict not in POSITIVE_VERDICTS:
                continue
            token = rec.get("token") or ""
            img = verify_service.image_path(token)
            target = rec.get("rows") or []
            line = {
                "token": token,
                "image": str(img) if img else None,
                "source": rec.get("source"),
                "page": rec.get("page"),
                "verdict": verdict,
                "columns": _columns(target),
                "target_rows": target,
                "pred_rows": rec.get("pred_rows"),
            }
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
            n += 1
            rows_total += len(target)
            if img:
                with_image += 1
            if rec.get("pred_rows") is not None:
                with_pred += 1

    manifest = {
        "dataset": str(ds_path),
        "samples": n,
        "by_verdict": by_verdict,
        "with_image": with_image,
        "with_pred_rows": with_pred,
        "rows_total": rows_total,
        "note": "Базонезависимый актив: картинка→target. with_pred_rows — доступно для таксономии/LoRA-диффа.",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


# ── 2. таксономия ошибок ─────────────────────────────────────────────────────

def _num(s: Any) -> Optional[float]:
    try:
        return float(str(s).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _is_confusion(a: str, b: str) -> bool:
    """a и b одной длины и отличаются только «путаемыми» символами (5↔S, о↔o, …)."""
    if len(a) != len(b) or a == b:
        return False
    diffs = 0
    for ca, cb in zip(a, b):
        if ca == cb:
            continue
        diffs += 1
        if cb not in _CONFUSABLES.get(ca, "") and ca not in _CONFUSABLES.get(cb, ""):
            return False
    return 0 < diffs <= max(1, len(a) // 2)


def classify_cell(pred: Any, true: Any) -> Optional[str]:
    """Класс расхождения ячейки pred→true. None — совпадает."""
    ps, ts = ("" if pred is None else str(pred)).strip(), ("" if true is None else str(true)).strip()
    if ps == ts:
        return None
    if ps.casefold() == ts.casefold() or " ".join(ps.split()) == " ".join(ts.split()):
        return "whitespace_case"
    pn, tn = _num(ps), _num(ts)
    if pn is not None and tn is not None:
        return "numeric_value"
    if _is_confusion(ps, ts):
        return "char_confusion"  # путаница цифр/латиницы-кириллицы — главный кандидат на LoRA
    if not ps and ts:
        return "empty_pred"
    return "text_value"


def _diff_record(pred_rows: list[dict], target_rows: list[dict]) -> dict[str, int]:
    """Классы расхождений одной пары pred→target (структура + ячейки)."""
    counts: dict[str, int] = {}

    def bump(k: str, by: int = 1):
        counts[k] = counts.get(k, 0) + by

    pcols, tcols = set(_columns(pred_rows)), set(_columns(target_rows))
    if tcols - pcols:
        bump("missing_column", len(tcols - pcols))
    if pcols - tcols:
        bump("extra_column", len(pcols - tcols))
    if len(target_rows) > len(pred_rows):
        bump("missing_row", len(target_rows) - len(pred_rows))
    elif len(pred_rows) > len(target_rows):
        bump("extra_row", len(pred_rows) - len(target_rows))

    common = pcols & tcols
    for pr, tr in zip(pred_rows, target_rows):
        for c in common:
            cls = classify_cell(pr.get(c), tr.get(c))
            if cls:
                bump(cls)
    return counts


def error_taxonomy() -> dict[str, Any]:
    """Свод классов ошибок по всем corrected-записям с pred_rows. Видно: systematic ли косяк."""
    totals: dict[str, int] = {}
    analyzed = 0
    no_pred = 0
    corrected = 0
    for rec in _records():
        if str(rec.get("verdict")) != "corrected":
            continue
        corrected += 1
        pred = rec.get("pred_rows")
        target = rec.get("rows") or []
        if pred is None:
            no_pred += 1
            continue
        analyzed += 1
        for k, v in _diff_record(pred, target).items():
            totals[k] = totals.get(k, 0) + v

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    total_diffs = sum(totals.values())
    top = ranked[0] if ranked else None
    return {
        "corrected_records": corrected,
        "analyzed": analyzed,
        "skipped_no_pred": no_pred,   # старые записи без захвата предсказания
        "total_diffs": total_diffs,
        "by_class": dict(ranked),
        "dominant": ({"class": top[0], "share": round(top[1] / total_diffs, 3)} if top and total_diffs else None),
        "lora_signal": bool(top and total_diffs and top[1] / total_diffs >= 0.4 and analyzed >= 20),
        "note": "lora_signal=true → один класс доминирует на достаточной выборке: кандидат под LoRA. "
                "Иначе — добивать промптом/препроцессингом или копить разметку.",
    }
