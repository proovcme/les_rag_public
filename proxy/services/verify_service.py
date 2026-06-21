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


def _extract_oriented(image) -> list[dict]:
    """Высокий лист → тайлинг полосами, иначе один vision-вызов."""
    w, h = image.size
    if h / max(w, 1) > float(os.getenv("VERIFY_VL_TILE_ASPECT", "1.7")):
        return _tiled_extract(image)
    return _vision_call(image)


def _vision_extract_rows(image) -> list[dict]:
    """Диспетчер с авто-поворотом. На больших листах таблицы часто повёрнуты на 90°
    (текст боком) — qwen3-vl читает их как обрывки/пусто. Если прямой проход пуст,
    пробуем повёрнутые ориентации (CW/CCW) и берём первую непустую (доказано: даёт
    34 строки там, где прямой проход — 0). Отключается VERIFY_VL_AUTOROTATE=0."""
    rows = _extract_oriented(image)
    if rows or os.getenv("VERIFY_VL_AUTOROTATE", "1") != "1":
        return rows
    from PIL import Image as _Img
    for tr in (_Img.ROTATE_270, _Img.ROTATE_90):  # 90° CW, затем CCW
        try:
            rows = _extract_oriented(image.transpose(tr))
        except Exception:
            rows = []
        if rows:
            return rows
    return rows


def _tiled_extract(image) -> list[dict]:
    """Горизонтальные полосы с перекрытием → vision по каждой → строки, дедуп по сигнатуре."""
    w, h = image.size
    n = min(5, max(2, round(h / max(w, 1))))   # число полос ~ соотношение сторон
    overlap = int((h / n) * 0.12)              # перекрытие, чтобы не резать строки пополам
    rows: list[dict] = []
    seen: set[str] = set()
    for i in range(n):
        top = max(0, int(i * h / n) - overlap)
        bot = min(h, int((i + 1) * h / n) + overlap)
        try:
            tile_rows = _vision_call(image.crop((0, top, w, bot)))
        except Exception:
            tile_rows = []
        for r in tile_rows:
            sig = json.dumps(r, ensure_ascii=False, sort_keys=True)
            if sig not in seen:
                seen.add(sig)
                rows.append(r)
    return rows


def _vision_call(image) -> list[dict]:
    """Один vision-вызов qwen3-vl-nt + prefill пустого <think> (рабочий рецепт,
    см. docs/extraction_and_lora) по одной картинке → строки JSON."""
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
    glossary = os.getenv(
        "VERIFY_VL_GLOSSARY",
        "Контекст — строительная исполнительная документация (ведомости объёмов, "
        "экспликации помещений, чек-листы приёмки электрики/слаботочки/ОВ). Возможные "
        "(НЕ обязательные!) графы: Поз./номер, Помещение/Имя, Наименование, Тип/марка, "
        "Ед.изм., Количество, Отметка о приёмке, Замечание, Корпус — но используй "
        "РЕАЛЬНУЮ шапку именно ЭТОЙ таблицы, графы бывают совсем другими. "
        "Сокращения для чтения: приёмка часто АОРПИ + графы ГП/ФН с подписью и датой; "
        "марки щитов/шкафов ШР, ШО, ШС, ШРП, ШРМ, ШПО, РШТ, ЩРН, ЩО. ",
    )
    prompt = (
        "Ты распознаёшь СКАН строительной таблицы (ведомость/экспликация/чек-лист). "
        + glossary +
        "Сначала прочитай ШАПКУ ЭТОЙ таблицы ДОСЛОВНО и используй ТОЛЬКО её реальные "
        "графы как ключи JSON (не выдумывай графы из списка выше, если их нет в таблице). "
        "Внимательно различай похожие кириллические буквы: А/Л, П/И, О/С, Н/И, Р/Я "
        "(напр. это АОРПИ, КОРПУС — не «ЛОРПИ», не «КОРИУС»). "
        "ЦИФРЫ пиши ЦИФРАМИ, не латиницей: «5» это пять (НЕ латинская «S»), «0» это ноль "
        "(НЕ буква «О»), «6» это шесть. В марках сохраняй точки и цифры дословно "
        "(напр. 1.2ШР5, ШС65, РШТ5.1 — не «ШС6S», не «12ШРПS»). "
        "Извлеки ВСЕ строки данных в JSON-массив объектов (ключ = графа из шапки). "
        "ВКЛЮЧИ рукописные значения — количества, подписи, даты, замечания — пиши как видишь. "
        "КРИТИЧНО: пиши ТОЛЬКО то, что реально видишь на скане. НЕ выдумывай строки, "
        "наименования, числа и цены. Если таблица нечитаема или её нет — верни пустой "
        "массив []. Лучше пусто, чем выдуманные данные. "
        "Ответь ТОЛЬКО валидным JSON-массивом."
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
    # Фолбэк на штатный as-built OCR убран: его движок (gemma4:12b) сломан —
    # пустой вывод + лишняя загрузка GPU (конфликт с MLX). Пусто → оператор
    # заполнит вручную; распознавание чиним промптом/моделью, не фолбэком.

    rows = [_flatten_row(r) for r in rows if isinstance(r, dict)]  # вложенные {ГП,ФН} → строка
    # колонки = объединение ключей по порядку появления
    columns: list[str] = []
    for r in rows:
        for k in r:
            if k not in columns:
                columns.append(k)
    return {"token": token, "rows": rows, "columns": columns}


def _flatten_row(row: dict) -> dict:
    """Вложенные dict/list в ячейке → читаемая строка (иначе aggrid рисует [object Object]).
    Названия колонок нормализуем: схлопываем переносы/лишние пробелы."""
    out: dict = {}
    for k, v in row.items():
        key = " ".join(str(k).split())  # «Наименование\nназначения» → «Наименование назначения»
        if isinstance(v, dict):
            out[key] = " ".join(f"{kk}:{vv}" for kk, vv in v.items() if str(vv).strip())
        elif isinstance(v, list):
            out[key] = ", ".join(str(x) for x in v)
        else:
            out[key] = v
    return out


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
