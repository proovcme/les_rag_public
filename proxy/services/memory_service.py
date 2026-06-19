"""Рабочая память Л.Е.С. — заметки оператора и ретрив по истории (W16.1 + W16.3, LES3_PLAN).

ADR-11: «запомни: …» — детерминированная regex-команда, recall — лексический
скоринг по пересечению слов (SQL + python), LLM не участвует. Хранение —
в метабазе рядом с chat_history и les_tasks.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from typing import Any

from backend.rag_config import rag_meta_db_path

logger = logging.getLogger(__name__)

# «запомни: …», «запомни, что …» — разделитель обязателен, иначе перехватим
# обычные вопросы вида «запомни ли ты прошлый разговор?»
REMEMBER_RE = re.compile(
    r"^\s*запомни\s*(?:[:,—-]\s*(?:что\s+)?|что\s+)(?P<text>.{3,1000})$",
    re.IGNORECASE | re.DOTALL,
)
# «заметки», «что ты помнишь», «покажи заметки», «мои заметки»
LIST_NOTES_RE = re.compile(
    r"^\s*(?:(?:покажи|мои)\s+заметки|заметки|что\s+ты\s+помнишь)\s*\??\s*$",
    re.IGNORECASE,
)
# «забудь заметку 5», «удали заметку 5»
FORGET_NOTE_RE = re.compile(
    r"^\s*(?:забудь|удали)\s+заметку\s*[№#]?\s*(?P<id>\d+)\s*$",
    re.IGNORECASE,
)

_BAD_FEEDBACK = ("bad_answer", "incorrect", "wrong_dataset", "bad_source")
_STOPWORDS = frozenset(
    "что как это для при или если того этом быть есть какой какие каких "
    "может можно нужно надо есть ли по на из в с к у и а но не да же ещё еще "
    "тебе меня него ним них там тут вот так уже только очень всех весь вся".split()
)
_WORD_RE = re.compile(r"[а-яёa-z0-9]{4,}", re.IGNORECASE)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(rag_meta_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS les_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            dataset_filter TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )
        """
    )
    for col, ddl in (
        ("project_id", "ALTER TABLE les_notes ADD COLUMN project_id INTEGER NOT NULL DEFAULT 0"),
        ("auto", "ALTER TABLE les_notes ADD COLUMN auto INTEGER NOT NULL DEFAULT 0"),
    ):
        try:  # Q3: партиция по объекту; auto=1 — авто-заметка (распознанный факт, не «запомни:»)
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass
    return conn


def create_note(text: str, dataset_filter: str = "", project_id: int = 0, auto: bool = False) -> dict[str, Any]:
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO les_notes(text, dataset_filter, project_id, auto, created_at) VALUES (?,?,?,?,?)",
            (text.strip(), dataset_filter, int(project_id), 1 if auto else 0, now),
        )
        conn.commit()
        note_id = cur.lastrowid
    logger.info("[MEMORY] %sзаметка #%s: %s", "авто-" if auto else "", note_id, text[:80])
    try:  # W17.2: детерминированные рёбра из текста заметки (НТД/[[вики]]/элемент), 0 LLM
        from proxy.services.edge_service import derive_edges_from_text
        derive_edges_from_text("note", str(note_id), text, provenance=f"note#{note_id}")
    except Exception as edge_err:
        logger.warning("[EDGES] derive note#%s skipped: %s", note_id, edge_err)
    return {"id": note_id, "text": text.strip(), "dataset_filter": dataset_filter,
            "project_id": int(project_id), "created_at": now}


def list_notes(limit: int = 50, project_id: int | None = None) -> list[dict[str, Any]]:
    with _connect() as conn:
        if project_id is not None:  # Q3: фильтр по объекту (None → все)
            rows = conn.execute(
                "SELECT * FROM les_notes WHERE project_id=? ORDER BY id DESC LIMIT ?",
                (int(project_id), limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM les_notes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def delete_note(note_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM les_notes WHERE id=?", (note_id,))
        conn.commit()
    return cur.rowcount > 0


def _keywords(text: str) -> set[str]:
    # Грубый стемминг срезом до 6 символов: «корпуса»/«корпусу» → «корпус».
    # Для recall-скоринга по пересечению этого достаточно (ADR-11: без моделей).
    words = {w.lower() for w in _WORD_RE.findall(text)} - _STOPWORDS
    return {w[:6] for w in words}


def _overlap_score(query_words: set[str], text: str) -> float:
    if not query_words:
        return 0.0
    text_words = _keywords(text)
    if not text_words:
        return 0.0
    hit = len(query_words & text_words)
    return hit / len(query_words)


def recall_context(
    question: str,
    *,
    max_notes: int = 3,
    max_history: int = 1,
    min_score: float = 0.34,
    history_rows: int = 300,
) -> str:
    """Лексический recall: релевантные заметки оператора + прошлые удачные ответы.

    Возвращает готовый текстовый блок для промпта ('' — нечего подмешивать).
    Детерминированно: пересечение значимых слов, без эмбеддингов и LLM.
    """
    query_words = _keywords(question)
    if not query_words:
        return ""

    scored_notes = [
        (score, note)
        for note in list_notes(limit=200)
        if (score := _overlap_score(query_words, note["text"])) >= min_score
    ]
    scored_notes.sort(key=lambda pair: -pair[0])

    scored_history: list[tuple[float, dict[str, Any]]] = []
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT id, question, answer, feedback_status FROM chat_history "
                "WHERE success=1 AND crag_status IN ('VERIFIED','DETERMINISTIC') "
                f"AND feedback_status NOT IN ({','.join('?' * len(_BAD_FEEDBACK))}) "
                "AND question != ? ORDER BY id DESC LIMIT ?",
                (*_BAD_FEEDBACK, question.strip(), history_rows),
            ).fetchall()
        for row in rows:
            score = _overlap_score(query_words, row["question"])
            if score >= max(min_score, 0.5):  # к истории строже: совпадение по смыслу вопроса
                scored_history.append((score, dict(row)))
        scored_history.sort(key=lambda pair: -pair[0])
    except sqlite3.OperationalError:  # chat_history ещё не создана (свежая база)
        pass

    parts: list[str] = []
    for _, note in scored_notes[:max_notes]:
        parts.append(f"- Заметка оператора #{note['id']}: {note['text'][:400]}")
    for _, row in scored_history[:max_history]:
        parts.append(
            f"- Из истории (на вопрос «{row['question'][:150]}» ранее отвечено): {row['answer'][:600]}"
        )
    if not parts:
        return ""
    return "Рабочая память (заметки оператора и прошлые решения):\n" + "\n".join(parts)


def session_memory(session_id: str, *, max_turns: int = 6, max_chars: int = 2000) -> str:
    """Память диалога: последние реплики ТЕКУЩЕЙ сессии для контекста («помни всё»).

    Чат потурно безсостоятельный — без этого ЛЕС не помнит, о чём шла речь выше.
    Детерминированно: просто последние Q/A сессии из chat_history. Без LLM.
    """
    if not (session_id or "").strip():
        return ""
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT question, answer FROM chat_history WHERE session_id=? "
                "ORDER BY id DESC LIMIT ?",
                (session_id.strip(), max_turns),
            ).fetchall()
    except sqlite3.OperationalError:
        return ""
    rows = list(reversed(rows))
    if not rows:
        return ""
    parts: list[str] = []
    for row in rows:
        q = " ".join(str(row["question"] or "").split())[:300]
        a = " ".join(str(row["answer"] or "").split())[:400]
        if q:
            parts.append(f"Пользователь: {q}")
        if a:
            parts.append(f"Л.Е.С.: {a}")
    block = "Предыдущий разговор в этой сессии (помни контекст диалога):\n" + "\n".join(parts)
    return block[:max_chars]


# ── Авто-заметки: ЛЕС сам сохраняет утверждения-факты (без «запомни:»), 0 LLM ──

# Начала вопросов/команд — НЕ факт (это запрос, даже без «?»).
_NON_FACT_STARTS = (
    "что", "как", "какой", "кака", "каки", "како", "где", "когда", "почему", "зачем",
    "сколько", "кто", "чей", "чем", "куда", "можно ли", "нужно ли", "есть ли",
    "сделай", "покажи", "сверь", "сверить", "найди", "дай ", "сформируй", "построй",
    "переведи", "посчитай", "выведи", "запиши", "удали", "забудь", "добавь", "создай",
    "открой", "сгенерируй", "сравни", "проверь", "проанализируй", "расскажи", "опиши",
    "перечисли", "напомни", "помоги", "объясни",
)
# Маркеры утверждения-факта (связки/атрибуты) — без них в авто-заметку не берём,
# иначе запрос без «?» («требования к серверным сп 485») ложно уйдёт в факт.
_FACT_MARKERS = (
    " — ", " – ", " - ", " это ", "называ", " зов", "равно", "составля", "являет",
    "отвечает за", "ответствен", "контакт", "телефон", "адрес", " у нас ", " у меня ",
    " наш ", " наша ", " наше ", " наши ", "договор", "срок ", "дедлайн", "бюджет",
)
# Слова-запросы где угодно в тексте → это ПРОСЬБА, не факт («Котельная — справка по объекту»).
# Иначе паттерн «X — Y» ложно уходит в авто-заметку.
_REQUEST_ANYWHERE = (
    "справк", "сводк", "сделай", "покажи", "дай ", "оформи", "подготов", "сформир",
    "выведи", "составь", "перечисли", "рассчита", "посчита", "сгенер", "напиши",
)


def autonote_enabled() -> bool:
    return os.getenv("LES_AUTONOTE_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def looks_like_fact(text: str) -> bool:
    """Похоже ли сообщение на утверждение-факт для авто-заметки. Консервативно (precision)."""
    t = (text or "").strip()
    if len(t) < 8 or "?" in t:
        return False
    low = t.lower()
    if any(low.startswith(w) for w in _NON_FACT_STARTS):
        return False
    if any(m in low for m in _REQUEST_ANYWHERE):  # запрос где угодно → не факт
        return False
    if len([w for w in _WORD_RE.findall(t) if w.lower() not in _STOPWORDS]) < 2:
        return False
    return any(m in low for m in _FACT_MARKERS)


def maybe_autonote(question: str, dataset_filter: str = "", project_id: int = 0) -> dict[str, Any] | None:
    """Авто-заметка из утверждения-факта (не вопрос, не команда, есть маркер). Без LLM."""
    if not autonote_enabled() or not looks_like_fact(question):
        return None
    note = create_note(question.strip().rstrip("."), dataset_filter=dataset_filter or "",
                       project_id=project_id, auto=True)
    return {
        "answer": (f"✎ Принял к сведению (авто-заметка #{note['id']}): {note['text']}\n"
                   f"Забыть: «забудь заметку {note['id']}» · отключить авто-память: LES_AUTONOTE_ENABLED=false"),
        "operation": "note_autocreate",
        "count": 1,
        "note_id": note["id"],
    }


def maybe_handle_memory_command(question: str, dataset_filter: str = "", project_id: int = 0) -> dict[str, Any] | None:
    """Детерминированный обработчик команд заметок из чата (ADR-11: без LLM).
    В режиме объекта (project_id>0) заметки создаются и перечисляются в рамках объекта."""
    text = question.strip()

    match = REMEMBER_RE.match(text)
    if match:
        note = create_note(match.group("text").strip().rstrip("."), dataset_filter=dataset_filter or "", project_id=project_id)
        return {
            "answer": f"✎ Запомнил (заметка #{note['id']}): {note['text']}\nЗабыть: «забудь заметку {note['id']}»",
            "operation": "note_create",
            "count": 1,
            "note_id": note["id"],
        }

    match = FORGET_NOTE_RE.match(text)
    if match:
        note_id = int(match.group("id"))
        ok = delete_note(note_id)
        return {
            "answer": f"✓ Заметка #{note_id} удалена." if ok else f"Заметки #{note_id} нет.",
            "operation": "note_delete",
            "count": 1 if ok else 0,
        }

    match = LIST_NOTES_RE.match(text)
    if match:
        notes = list_notes(limit=30, project_id=project_id or None)
        if not notes:
            answer = "Заметок пока нет. Создать: «запомни: …»"
        else:
            answer = "**Заметки оператора:**\n" + "\n".join(
                f"✎ #{n['id']} {n['text'][:200]}" for n in notes
            )
        return {"answer": answer, "operation": "notes_list", "count": len(notes)}

    return None
