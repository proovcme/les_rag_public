"""Ручная верификация распознанных таблиц объёмов.

Оператор видит сплит: слева — рендер страницы скана, справа — таблица, которую
извлёк движок OCR/vision. Подтверждает «всё ок» или правит ячейки. Подтверждённый
результат сохраняется и становится:
  - принятой выпиской объёмов (рабочая функция);
  - ground truth для бенча извлечения (`tools/extract_bench.py`) и, если дойдём,
    обучающей выборкой LoRA — то есть верификация = разметка.

Картинка страницы кэшируется на диск и отдаётся по детерминированному токену
(хэш пути+страницы), без состояния в памяти. Подтверждения лежат в
`data/verifications/` (приватно, вне релизного экспорта).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
VERIFY_DIR = ROOT / "data" / "verifications"      # ground truth (приватно)
CACHE_DIR = ROOT / "data" / "verify_cache"        # PNG-рендеры страниц


def _token(path: str, page: int) -> str:
    return hashlib.sha256(f"{path}::{page}".encode("utf-8")).hexdigest()[:32]


def _safe_path(path: str) -> Path:
    """Путь-гард: переиспользуем корни файлового вьювера, иначе — отказ."""
    try:
        from proxy.routers.files import _safe
        return _safe(path)
    except Exception:
        p = Path(path).resolve()
        if not p.is_file():
            raise FileNotFoundError(path)
        return p


def _load_page_image(src: Path, page: int):
    """PDF → рендер страницы; картинка (.png/.tif/.jpg) → как есть. Возвращает PIL.Image."""
    suffix = src.suffix.lower()
    if suffix == ".pdf":
        from backend.ocr_parser import render_pdf_to_images
        images = render_pdf_to_images(src, dpi=150)
        if not images:
            raise ValueError("пустой PDF")
        return images[min(page, len(images) - 1)]
    from PIL import Image
    return Image.open(src).convert("RGB")


def _vision_extract_rows(image) -> list[dict]:
    """Извлечь строки таблицы локальным vision (qwen3-vl-nt + prefill пустого <think>).

    Рабочий рецепт (см. docs/extraction_and_lora): не-thinking рендерер ollama +
    prefill гасит «размышление» → чистый JSON; читает и рукописное на мусорных сканах.
    """
    import base64
    import io
    import re
    import urllib.request

    # Крупные сканы (большие листы) qwen3-vl не сходит к JSON — даунскейлим по ширине.
    max_w = int(os.getenv("VERIFY_VL_MAX_WIDTH", "1400"))
    w, h = image.size
    if w > max_w:
        image = image.resize((max_w, int(h * max_w / w)))

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()
    prompt = (
        "Скан строительного чек-листа — таблица объёмов/оборудования по помещениям. "
        "Извлеки ВСЕ строки таблицы в JSON-массив. Поля каждой строки бери из шапки "
        "таблицы (напр. помещение, оборудование/наименование, позиция, количество, "
        "единица, отметка_о_приемке). ВКЛЮЧИ рукописные значения (пиши как видишь). "
        "Только JSON-массив."
    )
    body = {
        "model": os.getenv("VERIFY_VL_MODEL", "qwen3-vl-nt"),
        "messages": [
            {"role": "user", "content": prompt, "images": [img_b64]},
            {"role": "assistant", "content": "<think>\n\n</think>\n\n"},  # гасим thinking
        ],
        "stream": False,
        "options": {"temperature": 0, "num_predict": 2200},
    }
    url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"content-type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=float(os.getenv("VERIFY_VL_TIMEOUT_SEC", "240"))) as r:
        content = (json.loads(r.read()).get("message", {}) or {}).get("content", "") or ""
    m = re.search(r"\[.*\]", content, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    return [row for row in data if isinstance(row, dict)]


def render_and_extract(path: str, page: int = 0, engine: str = "local") -> dict:
    """Рендер страницы + извлечение таблицы. Возвращает {token, rows, columns}.

    Извлечение — локальный vision (qwen3-vl-nt), с фолбэком на штатный as-built OCR.
    Смысл режима в том, что оператор ПРАВИТ результат, а не доверяет ему слепо.
    """
    src = _safe_path(path)
    image = _load_page_image(src, page)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    token = _token(path, page)
    image.save(CACHE_DIR / f"{token}.png")  # отдаётся роутом /verify-image?token= (same-origin)

    rows: list[dict] = []
    try:
        rows = _vision_extract_rows(image)
    except Exception:
        rows = []
    if not rows:  # vision не дал — пробуем штатный as-built OCR
        try:
            from proxy.services import asbuilt_ocr
            ocr_engine = asbuilt_ocr.resolve_engine(engine)
            text = asbuilt_ocr.vision_ocr_tables(image, ocr_engine)
            rows = asbuilt_ocr.parse_rows_json(text)
        except Exception:
            rows = []

    # колонки = объединение ключей по порядку появления
    columns: list[str] = []
    for r in rows:
        for k in r:
            if k not in columns:
                columns.append(k)
    return {"token": token, "rows": rows, "columns": columns}


def image_path(token: str) -> Optional[Path]:
    p = CACHE_DIR / f"{token}.png"
    return p if p.exists() else None


def save_verification(path: str, page: int, rows: list[dict], verdict: str = "ok") -> dict:
    """Сохранить подтверждённую/исправленную таблицу — ground truth."""
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    token = _token(path, page)
    record = {
        "token": token,
        "source": path,
        "page": page,
        "verdict": verdict,           # ok | corrected | rejected
        "rows": rows,
        "saved_at": int(time.time()),
    }
    (VERIFY_DIR / f"{token}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record


def get_verification(path: str, page: int) -> Optional[dict]:
    f = VERIFY_DIR / f"{_token(path, page)}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_verifications() -> list[dict]:
    if not VERIFY_DIR.exists():
        return []
    out: list[dict] = []
    for f in sorted(VERIFY_DIR.glob("*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
            out.append({
                "token": rec.get("token"),
                "source": rec.get("source"),
                "page": rec.get("page"),
                "verdict": rec.get("verdict"),
                "n_rows": len(rec.get("rows", [])),
                "saved_at": rec.get("saved_at"),
            })
        except Exception:
            continue
    return out
