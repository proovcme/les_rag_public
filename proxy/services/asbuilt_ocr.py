"""asbuilt_ocr.py — structured vision-OCR таблиц со скан-исполнительных (один LLM-шаг).

Единственное место, где в приёмке смонтированного объёма участвует модель: она ТОЛЬКО
переписывает ячейки таблиц в JSON, ничего не считая. Всю арифметику/типизацию/свод делает
код (ADR-11, LLM-минимализм). Движок выбирается параметром:

- ``local``  — OpenAI-совместимый vision у локального ollama (`OLLAMA_BASE_URL`, gemma4:12b);
- ``cloud``  — OpenAI-совместимый vision в облаке через proxyapi (`OPENAI_BASE_URL`, gpt-4.1).

Тело запроса переиспользует ``backend.ocr_parser.build_vlm_ocr_body`` (движко-агностично).
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

from backend.ocr_parser import _pil_to_png_b64, build_vlm_ocr_body

logger = logging.getLogger(__name__)

# Строгий промпт: брать строки ТОЛЬКО из таблиц «…смонтированного…», игнорировать легенду/план.
TABLE_OCR_PROMPT = (
    "Это фрагмент скана исполнительной схемы. На фрагменте могут быть таблицы фактически "
    "смонтированных объёмов: «Таблица смонтированного оборудования, изделий и материалов» и "
    "«Ведомость смонтированного оборудования». "
    "Бери строки ТОЛЬКО из таблиц, в заголовке которых есть слово «смонтированного». "
    "ИГНОРИРУЙ условные обозначения, экспликацию помещений, план этажа, легенду, штамп и "
    "спецификацию узлов обхода балок. "
    "Верни ТОЛЬКО JSON-массив объектов вида "
    '{"table": "<заголовок таблицы>", "no": "<№ п/п>", "name": "<наименование>", '
    '"type": "<тип/марка>", "unit": "<ед. изм.>", "qty": "<кол-во>"}. '
    "Числа переписывай как в документе (десятичная запятая допустима). "
    "Если подходящих таблиц на фрагменте НЕТ — верни пустой массив []. "
    "Ничего не вычисляй и не суммируй. Без пояснений и markdown — только JSON-массив."
)


@dataclass(frozen=True)
class OcrEngine:
    name: str          # local | cloud
    model: str
    base_url: str
    api_key: str = ""
    timeout: float = 180.0


def resolve_engine(engine: str = "local", *, model: Optional[str] = None) -> OcrEngine:
    """Собрать конфиг движка из env. ``local`` — ollama/gemma; ``cloud`` — OpenAI/proxyapi."""
    eng = (engine or "local").strip().lower()
    if eng == "cloud":
        base = os.getenv("OPENAI_BASE_URL", "https://openai.api.proxyapi.ru/v1").rstrip("/")
        return OcrEngine(
            name="cloud",
            model=model or os.getenv("LES_ASBUILT_CLOUD_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1")),
            base_url=base,
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            timeout=float(os.getenv("LES_ASBUILT_OCR_TIMEOUT", "180")),
        )
    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    return OcrEngine(
        name="local",
        model=model or os.getenv("RAG_OCR_MODEL", "gemma4:12b"),
        base_url=base,
        api_key=os.getenv("OLLAMA_API_KEY", "").strip(),
        timeout=float(os.getenv("LES_ASBUILT_OCR_TIMEOUT", "180")),
    )


def _completions_url(base_url: str) -> str:
    """OpenAI-совместимый путь. proxyapi-база уже с /v1 → /chat/completions; ollama → /v1/…"""
    base = base_url.rstrip("/")
    return f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"


# Шаг 1 (locate): по уменьшенному листу — нормированные рамки нужных таблиц.
LOCATE_PROMPT = (
    "Это скан исполнительной схемы (лист уменьшен). Найди на нём таблицы, в заголовке которых "
    "есть слово «смонтированного» — обычно «Таблица смонтированного оборудования, изделий и "
    "материалов» и «Ведомость смонтированного оборудования». "
    "Для КАЖДОЙ такой таблицы верни рамку в долях от размера изображения (0..1). "
    'Ответ — ТОЛЬКО JSON-массив объектов {"title": "<заголовок>", '
    '"bbox": [x0, y0, x1, y1]}, где x0,y0 — левый верх, x1,y1 — правый низ (0..1). '
    "Рамку бери с запасом, чтобы целиком вошли все столбцы (включая «Кол-во») и все строки. "
    "Не включай план этажа, условные обозначения, экспликацию и штамп. "
    "Если таких таблиц нет — верни []. Без пояснений — только JSON."
)


def vision_locate_tables(image, engine: OcrEngine, *, max_tokens: int = 1024) -> list[dict]:
    """Шаг локализации: уменьшенный лист → список {title, bbox(0..1)} нужных таблиц."""
    import httpx

    body = build_vlm_ocr_body(
        engine.model, _pil_to_png_b64(image), prompt=LOCATE_PROMPT, max_tokens=max_tokens
    )
    headers = {"Authorization": f"Bearer {engine.api_key}"} if engine.api_key else {}
    resp = httpx.post(_completions_url(engine.base_url), json=body, headers=headers, timeout=engine.timeout)
    resp.raise_for_status()
    content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    out = []
    for r in parse_rows_json(str(content or "")):
        bbox = r.get("bbox") or r.get("box")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                out.append({"title": str(r.get("title", "")), "bbox": [float(x) for x in bbox]})
            except (TypeError, ValueError):
                continue
    return out


def vision_ocr_tables(image, engine: OcrEngine, *, max_tokens: int = 4096) -> str:
    """Один vision-вызов: PIL-страница → сырой текст ответа модели (ожидается JSON-массив)."""
    import httpx

    body = build_vlm_ocr_body(
        engine.model, _pil_to_png_b64(image), prompt=TABLE_OCR_PROMPT, max_tokens=max_tokens
    )
    headers = {"Authorization": f"Bearer {engine.api_key}"} if engine.api_key else {}
    resp = httpx.post(_completions_url(engine.base_url), json=body, headers=headers, timeout=engine.timeout)
    resp.raise_for_status()
    content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    return str(content or "").strip()


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_rows_json(raw: str) -> list[dict]:
    """Устойчивый разбор ответа модели в список строк. Снимает ```json-обёртки, вычленяет массив."""
    if not raw:
        return []
    text = raw.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    # вычленить внешний массив, если модель добавила преамбулу/хвост
    if not text.startswith("["):
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("[ASBUILT-OCR] не удалось распарсить JSON-ответ модели (%d симв.)", len(raw))
        return []
    if isinstance(data, dict):  # модель могла обернуть в {"rows": [...]}
        for key in ("rows", "data", "items", "table"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]
