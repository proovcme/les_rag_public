"""asbuilt_chat_service.py — чат-канал приёмки смонтированного объёма из сканов-исполнительных.

Чтобы Совушка САМА вызывала приёмку, когда в разговоре просят: «вытащи смонтированный объём из
<папки>», «прогни исполнительные сканы …», «извлеки объёмы из чек-листов …».

Разбор интента/пути — 0 LLM (regex). Vision-OCR медленный (~80с/лист), поэтому прогон идёт
В ФОНЕ (поток + запись в журнал как `status=pending`); чат сразу отвечает «запустил N файлов».
Результат читается уже существующим каналом журнала («свод по L5», `/api/field/summary`).

Канон конвейера — `docs/ALGO-asbuilt-intake.md`.
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any, Optional

from proxy.services.asbuilt_intake_service import iter_pdfs, process_path

logger = logging.getLogger(__name__)

# интент: «смонтированн* объём/объёмы» ИЛИ глагол извлечения + контекст исполнительной/скана
_VERB = ("вытащи", "извлеки", "прогони", "прогни", "распознай", "сними объ", "посчитай объ")
_CTX = ("исполнительн", "чек-лист", "чеклист", "скан", " ид ", "оккл", "окл", "смонтирован")
_OBJEM = ("объём", "объем", "объёмы", "объемы")


def is_asbuilt_query(question: str) -> bool:
    q = " " + (question or "").lower().replace("ё", "е") + " "
    has_obj = any(o.replace("ё", "е") in q for o in _OBJEM)
    has_verb = any(v.replace("ё", "е") in q for v in _VERB)
    has_ctx = any(c.replace("ё", "е") in q for c in _CTX)
    # «смонтированный объём …» или «вытащи объём из исполнительных/сканов …»
    if "смонтирован" in q and has_obj:
        return True
    return has_verb and has_obj and has_ctx


# путь: в кавычках «…»/"…" или после «из/папк/файл/каталог»
# пути с пробелами — только в кавычках «…»/"…"; bare-путь берём до первого пробела
_PATH_QUOTED = re.compile(r"[«\"']([/~][^»\"'\n]+)[»\"']")
_PATH_BARE = re.compile(r"(?:из|папк\w*|файл\w*|каталог\w*)\s+([/~][^\s«»\"']+)")


def extract_path(question: str) -> str:
    m = _PATH_QUOTED.search(question or "")
    if m:
        return m.group(1).strip()
    m = _PATH_BARE.search(question or "")
    if m:
        return m.group(1).strip().rstrip(".,;")
    return ""


def _engine_from(question: str) -> str:
    q = (question or "").lower()
    if any(w in q for w in ("облак", "cloud", "gpt", "gpt-4", "точн")):
        return "cloud"
    return "local"


def _run_async(path: Path, *, engine: str, project_id: int) -> None:
    def _job() -> None:
        try:
            out = process_path(path, rotate="auto", engine=engine, write=True,
                               status="pending", project_id=project_id)
            logger.info("[ASBUILT-CHAT] фон завершён: %s → %d строк (%s)",
                        path.name, out.get("written", 0), engine)
        except Exception as err:  # noqa: BLE001 — фон не должен ронять процесс
            logger.error("[ASBUILT-CHAT] фон %s упал: %s", path, err)

    threading.Thread(target=_job, name="asbuilt-intake", daemon=True).start()


def maybe_handle_asbuilt_query(
    question: str, *, project_id: int = 0
) -> Optional[dict[str, Any]]:
    """Если это запрос на приёмку ИД — запустить в фоне и вернуть ack; иначе None."""
    if not is_asbuilt_query(question):
        return None

    raw = extract_path(question)
    if not raw:
        return {
            "answer": (
                "Похоже, нужно вытащить смонтированный объём из исполнительных схем. "
                "Укажи папку или файл со сканами — например: "
                "«вытащи смонтированный объём из «/Users/ovc/RAG/АУПС-СОУЭ»». "
                "Дольше — но точнее — добавь «облаком»."
            ),
            "operation": "asbuilt_need_path",
        }

    path = Path(raw).expanduser()
    if not path.exists():
        return {"answer": f"Путь не найден: {raw}", "operation": "asbuilt_no_path"}

    pdfs = iter_pdfs(path)
    if not pdfs:
        return {"answer": f"PDF-сканов в «{raw}» не нашёл.", "operation": "asbuilt_empty"}

    engine = _engine_from(question)
    _run_async(path, engine=engine, project_id=project_id)
    note = " (облаком, точнее)" if engine == "cloud" else " (локально; на больших листах долго)"
    return {
        "answer": (
            f"Запустил приёмку смонтированного объёма{note}: {len(pdfs)} "
            f"{'лист' if len(pdfs) == 1 else 'листов'} из «{path.name}». "
            "Иду по конвейеру: разворот → найти таблицу → прочитать → строки в журнал объёмов "
            "(status=pending, проверишь перед зачётом). "
            "Готово будет в фоне — спроси потом «свод по L5» или открой вкладку ОБЪЁМЫ. "
            "Числа в своде считает SQL, не модель."
        ),
        "operation": "asbuilt_started",
        "asbuilt": {"files": len(pdfs), "engine": engine, "path": str(path)},
    }
