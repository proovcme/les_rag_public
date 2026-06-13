"""Последняя CAD/BIM-подсветка для связки вьювер↔чат (W6.7).

Когда ответ чата опирается на CAD/BIM-чанки, из их текста механически
вынимаются `Source ID` элементов (0 LLM, чистый регэксп по проекции
`cad_bim_graph.render_projection`). Список кладётся в ответ чата И в общий
in-process снимок «последняя подсветка». АТЛАС-вьювер поллит
`GET /api/cad-bim/highlight`, сравнивает `seq` и перекрашивает элементы
загруженной модели — оператор не выбирает их вручную.

Стор намеренно простой (один снимок, монотонный `seq`): система локальная,
один оператор; БД и история тут не нужны.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Iterable

# `- Source ID: <id>` (проекция) и `Source ID / GlobalId: <id>` (карточка элемента).
_SOURCE_ID_RE = re.compile(r"Source ID(?:\s*/\s*GlobalId)?\s*:\s*([^\n]+)", re.IGNORECASE)
_IMPORT_ID_RE = re.compile(r"Import ID\s*:\s*([^\n]+)", re.IGNORECASE)
_BLANKS = {"", "-", "—", "–", "none", "null"}


def _clean(raw: str) -> str:
    return str(raw or "").strip().strip("`").strip()


def extract_highlight(texts: Iterable[str]) -> tuple[list[str], str | None]:
    """Вынуть упорядоченные уникальные source_id (+ первый import_id) из текстов чанков."""
    ids: list[str] = []
    seen: set[str] = set()
    import_id: str | None = None
    for text in texts:
        content = text or ""
        if "Source ID" not in content:
            continue
        for match in _SOURCE_ID_RE.finditer(content):
            value = _clean(match.group(1))
            if value.casefold() in _BLANKS or value in seen:
                continue
            seen.add(value)
            ids.append(value)
        if import_id is None:
            im = _IMPORT_ID_RE.search(content)
            if im:
                candidate = _clean(im.group(1))
                if candidate.casefold() not in _BLANKS:
                    import_id = candidate
    return ids, import_id


_lock = threading.Lock()
_state: dict[str, Any] = {
    "seq": 0,
    "ts": 0.0,
    "source_ids": [],
    "import_id": None,
    "question": "",
}


def set_highlight(
    source_ids: Iterable[str],
    *,
    import_id: str | None = None,
    question: str = "",
) -> dict[str, Any] | None:
    """Обновить снимок подсветки. Пустой список игнорируется (старая подсветка сохраняется)."""
    ids: list[str] = []
    seen: set[str] = set()
    for sid in source_ids or []:
        value = _clean(str(sid))
        if not value or value in seen:
            continue
        seen.add(value)
        ids.append(value)
    if not ids:
        return None
    with _lock:
        _state["seq"] += 1
        _state["ts"] = time.time()
        _state["source_ids"] = ids
        _state["import_id"] = import_id
        _state["question"] = (question or "")[:200]
        return dict(_state)


def get_highlight() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def reset_highlight() -> None:
    """Сброс снимка (для тестов)."""
    with _lock:
        _state.update({"seq": 0, "ts": 0.0, "source_ids": [], "import_id": None, "question": ""})
