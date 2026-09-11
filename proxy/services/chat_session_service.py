"""Durable chat ownership and explicit UI scope; history is never ownership evidence."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import UUID, uuid4

from backend.rag_config import rag_meta_db_path


class SessionConflictError(ValueError):
    """An existing session cannot be reassigned or recreated."""


def _empty_scope() -> dict:
    return dict(scope_type='none', project_ids=[], dataset_ids=[], selected_sources_only=False)


def _scope(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) - set(_empty_scope()):
        raise ValueError('Invalid session scope')
    result = _empty_scope() | value
    if result['scope_type'] not in {'none', 'all', 'project', 'projects', 'dataset', 'datasets', 'mixed'}:
        raise ValueError('Invalid scope_type')
    for key, item_type in [('project_ids', int), ('dataset_ids', str)]:
        items = result[key]
        if not isinstance(items, list) or len(items) > 500 or any(
            type(item) is not item_type or not item or (item_type is int and item < 1)
            for item in items
        ):
            raise ValueError(f'Invalid {key}')
        result[key] = list(dict.fromkeys(items))
    if type(result['selected_sources_only']) is not bool:
        raise ValueError('Invalid selected_sources_only')
    if result['scope_type'] in {'none', 'all'} and (result['project_ids'] or result['dataset_ids']):
        raise ValueError('Scope type conflicts with selected sources')
    return result


@contextmanager
def _connection(*, write=False):
    path = Path(rag_meta_db_path()).resolve()
    if not write and not path.exists():
        yield None
        return
    conn = sqlite3.connect(str(path) if write else path.as_uri() + '?mode=ro', uri=not write, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        if write:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('''CREATE TABLE IF NOT EXISTS les_chat_sessions (
                session_id TEXT PRIMARY KEY, project_id INTEGER,
                title TEXT NOT NULL, role TEXT NOT NULL, scope_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_chat_sessions_project ON les_chat_sessions(project_id, updated_at)')
        yield conn
        if write:
            conn.commit()
    except BaseException:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


def _has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _record(row):
    result = dict(row)
    result['scope'] = json.loads(result.pop('scope_json'))
    result['registered'] = True
    return result


def _legacy(conn, session_id=None):
    if not _has_table(conn, 'chat_history'):
        return []
    columns = {r['name'] for r in conn.execute('PRAGMA table_info(chat_history)')}
    if not {'session_id', 'timestamp', 'question', 'id'} <= columns:
        return []
    condition = 'AND h.session_id=?' if session_id is not None else ''
    excluded = ('AND NOT EXISTS (SELECT 1 FROM les_chat_sessions s WHERE s.session_id=h.session_id)'
                if _has_table(conn, 'les_chat_sessions') else '')
    rows = conn.execute(f'''SELECT h.session_id, MIN(h.timestamp) AS created_at,
        MAX(h.timestamp) AS updated_at,
        (SELECT substr(first.question, 1, 200) FROM chat_history first
         WHERE first.session_id=h.session_id ORDER BY first.id LIMIT 1) AS title
        FROM chat_history h WHERE h.session_id IS NOT NULL AND h.session_id != ''
        {condition} {excluded} GROUP BY h.session_id ORDER BY updated_at DESC LIMIT 500''',
        (session_id,) if session_id is not None else ()).fetchall()
    return [dict(row) | dict(project_id=None, role='agent', scope=_empty_scope(), registered=False) for row in rows]


def _get(conn, session_id):
    if _has_table(conn, 'les_chat_sessions'):
        row = conn.execute('SELECT * FROM les_chat_sessions WHERE session_id=?', (session_id,)).fetchone()
        if row:
            return _record(row)
    return next(iter(_legacy(conn, session_id)), None)


def get_session(session_id: str) -> dict | None:
    with _connection() as conn:
        return _get(conn, session_id) if conn is not None else None


def get_session_project_id(session_id: str) -> int | None:
    session = get_session(session_id)
    return session['project_id'] if session else None


def _timestamp_key(value: str | None) -> datetime:
    """SQLite CURRENT_TIMESTAMP is UTC without a suffix; registry uses ISO UTC."""
    try:
        parsed = datetime.fromisoformat(value or '')
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def list_sessions(project_id: int | None = None) -> list[dict]:
    """Return at most 500 sessions, scoped strictly to one project or ordinary chat."""
    with _connection() as conn:
        if conn is None:
            return []
        sessions = []
        if _has_table(conn, 'les_chat_sessions'):
            rows = conn.execute('SELECT * FROM les_chat_sessions WHERE project_id IS ? ORDER BY updated_at DESC LIMIT 500', (project_id,)).fetchall()
            sessions = [_record(row) for row in rows]
        if project_id is None:
            sessions.extend(_legacy(conn))
        return sorted(sessions, key=lambda item: _timestamp_key(item['updated_at']), reverse=True)[:500]


def _text(value, name, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'Invalid {name}')
    return value.strip()


def _insert(conn, session):
    conn.execute('INSERT INTO les_chat_sessions VALUES (?, ?, ?, ?, ?, ?, ?)', (
        session['session_id'], session['project_id'], session['title'], session['role'],
        json.dumps(session['scope'], ensure_ascii=False), session['created_at'], session['updated_at']))


def create_session(project_id=None, title='', session_id=None) -> dict:
    title = _text(title, 'title', 200)
    sid = str(UUID(str(session_id))) if session_id is not None else str(uuid4())
    if project_id is not None and (type(project_id) is not int or project_id < 1):
        raise ValueError('Invalid project_id')
    with _connection(write=True) as conn:
        if _get(conn, sid) is not None:
            raise SessionConflictError('Session already exists')
        scope = _empty_scope()
        if project_id is not None:
            if not _has_table(conn, 'les_projects') or conn.execute('SELECT 1 FROM les_projects WHERE id=?', (project_id,)).fetchone() is None:
                raise LookupError('Project not found')
            datasets = [row['ref'] for row in conn.execute("SELECT ref FROM les_project_links WHERE project_id=? AND kind='dataset' ORDER BY id", (project_id,))] if _has_table(conn, 'les_project_links') else []
            if datasets:
                scope = dict(scope_type='datasets', project_ids=[], dataset_ids=datasets, selected_sources_only=False)
        now = datetime.now(timezone.utc).isoformat()
        session = dict(session_id=sid, project_id=project_id, title=title, role='agent', scope=scope, created_at=now, updated_at=now, registered=True)
        _insert(conn, session)
        return session


def update_session(session_id, title=None, scope=None, role=None) -> dict:
    if title is not None:
        title = _text(title, 'title', 200)
    if scope is not None:
        scope = _scope(scope)
    if role is not None:
        role = _text(role, 'role', 64)
        if not role:
            raise ValueError('Empty role')
    with _connection(write=True) as conn:
        session = _get(conn, session_id)
        if session is None:
            raise LookupError('Session not found')
        if not session['registered']:
            _insert(conn, session)
        session.update({key: value for key, value in dict(title=title, scope=scope, role=role).items() if value is not None})
        session.update(updated_at=datetime.now(timezone.utc).isoformat(), registered=True)
        conn.execute('UPDATE les_chat_sessions SET title=?, role=?, scope_json=?, updated_at=? WHERE session_id=?', (
            session['title'], session['role'], json.dumps(session['scope'], ensure_ascii=False), session['updated_at'], session_id))
        return session
