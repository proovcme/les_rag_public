"""preset_service.py — режимы работы ЛЕС одним переключателем: local / cloud / mix.

Оператору не нужно крутить отдельные env — пресет согласованно ставит чат-LLM, скан-OCR и
движок приёмки ИД. Опирается на то, что выяснено бенчем: локальный чат (Qwen3.5-9B) и локальный
OCR (tesseract) хороши; плотные исполнительные таблицы локально не тянутся → в mix их отдаём в облако.

Пишет в .env (как `settings`-роутер) + `os.environ` (живёт сразу, провайдер/OCR читаются per-request).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ENV_PATH = Path(os.getenv("LES_ENV_PATH", ".env")).expanduser()
DEFAULT_OPENAI_MODEL = "gpt-5.4"

# Пресет → согласованный набор env. Ключи: провайдер чата, скан-OCR, движок приёмки ИД.
PRESETS: dict[str, dict[str, str]] = {
    "local": {  # всё на машине: приватно, бесплатно; конкретный локальный LLM выбирается по доступному стеку
        "LES_LLM_PROVIDER": "__LOCAL_PROVIDER__",
        "LES_CLOUD_CONSENT": "false",
        "RAG_OCR_BACKEND": "tesseract",
        "LES_ASBUILT_OCR_ENGINE": "local",
    },
    "cloud": {  # максимум качества: чат и плотные таблицы в облаке (дорого, данные наружу)
        "LES_LLM_PROVIDER": "openai",
        "LES_CLOUD_CONSENT": "true",
        "RAG_OCR_BACKEND": "tesseract",       # массовый скан-OCR локально (облачного конвертер-OCR нет)
        "LES_ASBUILT_OCR_ENGINE": "cloud",
    },
    "mix": {  # приватность по умолчанию + облако только там, где локаль не тянет (плотные таблицы ИД)
        "LES_LLM_PROVIDER": "mlx",
        "LES_CLOUD_CONSENT": "false",
        "RAG_OCR_BACKEND": "tesseract",
        "LES_ASBUILT_OCR_ENGINE": "cloud",
    },
}
PRESET_ALIASES = {
    "локал": "local", "локальный": "local", "локально": "local", "офлайн": "local",
    "облако": "cloud", "облачный": "cloud", "облачно": "cloud",
    "микс": "mix", "смешанный": "mix", "гибрид": "mix", "гибридный": "mix",
}


def normalize_preset(name: str) -> str | None:
    n = (name or "").strip().lower()
    if n in PRESETS:
        return n
    return PRESET_ALIASES.get(n)


def current_preset() -> str | None:
    """Какой пресет сейчас активен (по env) — или None, если набор кастомный."""
    cur = {
        "LES_LLM_PROVIDER": os.getenv("LES_LLM_PROVIDER", ""),
        "LES_CLOUD_CONSENT": os.getenv("LES_CLOUD_CONSENT", ""),
        "RAG_OCR_BACKEND": os.getenv("RAG_OCR_BACKEND", ""),
        "LES_ASBUILT_OCR_ENGINE": os.getenv("LES_ASBUILT_OCR_ENGINE", "local"),
    }
    for name, preset in PRESETS.items():
        preset = _materialize_preset(name, preset)
        if all(cur.get(k) == v for k, v in preset.items()):
            return name
    return None


def _local_provider() -> str:
    provider = os.getenv("LES_LLM_PROVIDER", "").strip().lower()
    if provider in {"ollama", "mlx"}:
        return provider
    mlx_url = os.getenv("MLX_URL", "").strip()
    ollama_url = os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_URL", "")).strip()
    if ":11434" in mlx_url or ollama_url:
        return "ollama"
    return "mlx"


def _materialize_preset(name: str, preset: dict[str, str]) -> dict[str, str]:
    result = dict(preset)
    if name == "local" and result.get("LES_LLM_PROVIDER") == "__LOCAL_PROVIDER__":
        result["LES_LLM_PROVIDER"] = _local_provider()
    return result


def _persist_env(updates: dict[str, str]) -> None:
    """Слить ключи в .env (как settings-роутер) + применить в os.environ (живёт сразу)."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    seen = set()
    out = []
    for line in lines:
        key = line.split("=")[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={val}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    for key, val in updates.items():
        os.environ[key] = val


def apply_preset(name: str) -> dict[str, Any]:
    """Применить пресет: согласованно выставить чат/OCR/asbuilt. Возвращает что выставлено."""
    canon = normalize_preset(name)
    if canon is None:
        raise ValueError(f"неизвестный режим «{name}» (есть: {', '.join(PRESETS)})")
    updates = _materialize_preset(canon, PRESETS[canon])
    _persist_env(updates)
    logger.info("[PRESET] режим «%s»: %s", canon, updates)
    return {"preset": canon, "applied": dict(updates)}


def describe(name: str) -> str:
    d = {
        "local": "всё локально — текущий локальный LLM (MLX или Ollama) + tesseract; приватно, бесплатно",
        "cloud": "облако — выбранная OpenAI-compatible модель; качество, но $ и данные наружу",
        "mix": "микс — локальный чат+OCR, облако только для плотных таблиц ИД",
    }
    return d.get(name, name)
