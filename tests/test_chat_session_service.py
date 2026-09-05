import sqlite3

import pytest

from proxy.services import chat_session_service as service
from proxy.services import project_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / 'meta.sqlite'
    monkeypatch.setattr(service, 'rag_meta_db_path', lambda: str(path))
    monkeypatch.setattr(project_service, 'rag_meta_db_path', lambda: str(path))
    return path


def test_read_missing_is_read_only(db):
    assert service.get_session('missing') is None
    assert service.get_session_project_id('missing') is None
    assert service.list_sessions() == []
    assert not db.exists()


def test_project_defaults_are_copied_and_sessions_isolated(db):
    project = project_service.create_project('Test')
    project_service.link_entity(project['id'], 'dataset', 'source-one')
    owned = service.create_session(project_id=project['id'])
    ordinary = service.create_session()
    assert owned['scope']['dataset_ids'] == ['source-one']
    assert ordinary['scope']['scope_type'] == 'none'
    assert service.get_session_project_id(owned['session_id']) == project['id']
    assert [s['session_id'] for s in service.list_sessions()] == [ordinary['session_id']]
    assert [s['session_id'] for s in service.list_sessions(project['id'])] == [owned['session_id']]
    project_service.link_entity(project['id'], 'dataset', 'later')
    assert service.get_session(owned['session_id'])['scope']['dataset_ids'] == ['source-one']


def test_empty_project_scope_and_missing_project(db):
    project = project_service.create_project('Empty')
    assert service.create_session(project['id'])['scope']['scope_type'] == 'none'
    with pytest.raises(LookupError):
        service.create_session(999)


def test_update_persists_scope_title_role_and_rejects_duplicate(db):
    session = service.create_session(title='Original')
    sid = session['session_id']
    scope = dict(scope_type='datasets', project_ids=[], dataset_ids=['a', 'b'], selected_sources_only=True)
    service.update_session(sid, title='Edited', scope=scope, role='estimate')
    restored = service.get_session(sid)
    assert (restored['title'], restored['role'], restored['scope']) == ('Edited', 'estimate', scope)
    with pytest.raises(service.SessionConflictError):
        service.create_session(session_id=sid)
    with pytest.raises(ValueError):
        service.update_session(sid, scope={'scope_type': 'surprise'})
    with pytest.raises(LookupError):
        service.update_session('missing', title='No')


def test_legacy_history_is_ordinary_and_read_does_not_migrate(db):
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE chat_history (id INTEGER PRIMARY KEY, session_id TEXT, timestamp TEXT, question TEXT)')
        conn.execute("INSERT INTO chat_history VALUES (1, 'legacy', '2026-01-01', 'First question')")
    assert service.list_sessions()[0]['session_id'] == 'legacy'
    assert service.get_session('legacy')['registered'] is False
    assert service.get_session_project_id('legacy') is None
    assert service.list_sessions(123) == []
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='les_chat_sessions'").fetchone() is None
    updated = service.update_session('legacy', title='Renamed')
    assert updated['registered'] is True
    assert updated['project_id'] is None


def test_conflict_cannot_move_session_or_capture_legacy(db):
    from uuid import uuid4

    project = project_service.create_project('Project')
    ordinary = service.create_session()
    with pytest.raises(service.SessionConflictError):
        service.create_session(project['id'], session_id=ordinary['session_id'])
    legacy_id = str(uuid4())
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE chat_history (id INTEGER PRIMARY KEY, session_id TEXT, timestamp TEXT, question TEXT)')
        conn.execute('INSERT INTO chat_history VALUES (1, ?, ?, ?)', (legacy_id, '2026-01-01', 'Question'))
    with pytest.raises(service.SessionConflictError):
        service.create_session(project['id'], session_id=legacy_id)
    assert service.get_session(ordinary['session_id'])['project_id'] is None
    assert service.get_session(legacy_id)['registered'] is False


def test_invalid_update_is_atomic_and_read_preserves_database(db):
    session = service.create_session(title='Preserved')
    before = db.read_bytes()
    assert service.get_session(session['session_id']) == session
    assert service.list_sessions() == [session]
    assert db.read_bytes() == before
    with pytest.raises(ValueError):
        service.update_session(session['session_id'], title='Lost', scope={
            'scope_type': 'none', 'dataset_ids': ['a']})
    assert service.get_session(session['session_id']) == session


def test_legacy_and_registered_sessions_sort_by_instant(db):
    session = service.create_session(title='Earlier registry')
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE les_chat_sessions SET updated_at=?', ('2026-09-05T08:00:00+00:00',))
        conn.execute('CREATE TABLE chat_history (id INTEGER PRIMARY KEY, session_id TEXT, timestamp TEXT, question TEXT)')
        conn.execute('INSERT INTO chat_history VALUES (1, ?, ?, ?)', ('legacy', '2026-09-05 09:00:00', 'Later legacy'))
    assert [row['session_id'] for row in service.list_sessions()] == ['legacy', session['session_id']]
