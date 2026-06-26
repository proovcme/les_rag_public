"""Справочник ФСЭМ «машина → машинист» (ОТм/ЗПМ) — редактируемый `config/domain/fsem_machinist.yaml`.

0 LLM. Связывает код МАШИНЫ с ресурсом-машинистом (агрегированный ОТм в норме ГЭСН кода не несёт —
выделяем по коду машины). Знание вынесено из кода в yaml (handoff Codex, шаг #3): дополняется записями
из ФСЭМ без правки кода. `_SEED` — встроенный фолбэк (3 записи), если yaml отсутствует/битый.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

DEFAULT_PATH = Path("config/domain/fsem_machinist.yaml")

# Встроенный фолбэк (исторический _MACHINE_TO_MACHINIST из lsr_assembly_service) — на случай,
# если yaml не прочитался. Данные не теряются: yaml накладывается ПОВЕРХ seed.
_SEED: dict[str, tuple[str, str]] = {
    "91.05.05-015": ("4-100-060", "ОТм: кран на автомобильном ходу 16 т, машинист 6,0"),
    "91.14.02-001": ("4-100-040", "ОТм: автомобиль бортовой, машинист 4,0"),
    "91.14.02-002": ("4-100-040", "ОТм: автомобиль бортовой до 8 т, машинист 4,0"),
}


@lru_cache(maxsize=4)
def _load_raw(path: str | None = None) -> dict[str, dict[str, Any]]:
    p = Path(path) if path else DEFAULT_PATH
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        machines = data.get("machines") or {}
        return {str(k): dict(v) for k, v in machines.items() if isinstance(v, dict)}
    except Exception:
        return {}


def machine_to_machinist(path: str | None = None) -> dict[str, tuple[str, str]]:
    """Код машины → (код машиниста, наименование). yaml поверх встроенного seed (fail-safe)."""
    result: dict[str, tuple[str, str]] = dict(_SEED)
    for code, rec in _load_raw(path).items():
        m_code = str(rec.get("machinist_code") or "").strip()
        m_name = str(rec.get("machinist_name") or "").strip()
        if m_code and m_name:
            result[code] = (m_code, m_name)
    return result


def list_entries(path: str | None = None) -> list[dict[str, Any]]:
    """Полные записи справочника (для GUI/проверки): машина + поля машиниста."""
    raw = _load_raw(path)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for code, rec in raw.items():
        seen.add(code)
        out.append({"machine_code": code, **rec})
    for code, (m_code, m_name) in _SEED.items():
        if code not in seen:
            out.append({"machine_code": code, "machinist_code": m_code, "machinist_name": m_name})
    return sorted(out, key=lambda r: r.get("machine_code", ""))


def lookup(machine_code: str, path: str | None = None) -> Optional[tuple[str, str]]:
    return machine_to_machinist(path).get(str(machine_code or "").strip())
