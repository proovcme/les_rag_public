import sqlite3

import pytest

from proxy.services import memory_service as ms


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    path = tmp_path / 'meta.db'
    monkeypatch.setattr(ms, 'rag_meta_db_path', lambda: str(path))
    return path


def test_projection_scope_before_limit_and_disabled(db):
    global_note = ms.create_note('global preference')
    project_note = ms.create_note('project instruction', project_id=1)
    ms.create_note('foreign instruction', project_id=2)
    disabled = ms.create_note('excluded instruction', project_id=1)
    ms.update_note(disabled['id'], project_id=1, enabled=False)
    assert [n['id'] for n in ms.project_note_items(project_id=1, limit=2)] == [project_note['id'], global_note['id']]
    assert [n['id'] for n in ms.project_note_items(limit=1)] == [global_note['id']]


def test_scoped_edit_delete_and_recall():
    note = ms.create_note('concrete preference', project_id=0)
    assert ms.update_note(note['id'], project_id=9, text='wrong') is None
    assert not ms.delete_note(note['id'], project_id=9)
    changed = ms.update_note(note['id'], project_id=0, text='steel preference', enabled=False)
    assert changed['text'] == 'steel preference'
    assert 'steel preference' not in ms.recall_context('steel preference', max_history=0)
    assert ms.update_note(note['id'], project_id=0, enabled=True)['enabled']
    assert 'steel preference' in ms.recall_context('steel preference', max_history=0)
    assert ms.delete_note(note['id'], project_id=0)


def test_absent_database_projection_does_not_create(db):
    assert ms.project_note_items() == []
    assert not db.exists()


def test_legacy_schema_read_and_migration(db):
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE les_notes(id INTEGER PRIMARY KEY, text TEXT, dataset_filter TEXT, created_at REAL)')
        conn.execute("INSERT INTO les_notes VALUES (1, 'old preference', '', 1)")
    assert ms.project_note_items()[0]['text'] == 'old preference'
    with sqlite3.connect(db) as conn:
        assert 'enabled' not in {r[1] for r in conn.execute('PRAGMA table_info(les_notes)')}
    assert ms.list_notes()[0]['enabled'] == 1
    assert ms.list_notes()[0]['source_session_id'] is None


@pytest.mark.parametrize('text', ['', '  ', 'x' * 2001])
def test_edit_rejects_invalid_text(text):
    note = ms.create_note('valid')
    with pytest.raises(ValueError):
        ms.update_note(note['id'], project_id=0, text=text)


def test_legacy_commands_cannot_read_or_delete_other_scope():
    note = ms.create_note('private project note', project_id=2)
    assert ms.maybe_handle_memory_command('заметки')['count'] == 0
    assert ms.maybe_handle_memory_command(f"удали заметку {note['id']}", project_id=1)['count'] == 0
    assert ms.maybe_handle_memory_command(f"удали заметку {note['id']}", project_id=2)['count'] == 1


def test_explicit_only_filters_automatic_notes_before_limit():
    explicit = ms.create_note('explicit preference', project_id=1)
    automatic = ms.create_note('automatic preference', project_id=1, auto=True)
    assert ms.project_note_items(project_id=1, limit=1)[0]['id'] == automatic['id']
    assert ms.project_note_items(project_id=1, limit=1, explicit_only=True)[0]['id'] == explicit['id']


@pytest.mark.parametrize('changes', [{'text': 'confirmed preference'}, {'enabled': True}])
def test_explicit_update_adopts_historical_automatic_note(changes):
    note = ms.create_note('automatic preference', project_id=1, auto=True)
    assert ms.project_note_items(project_id=1, explicit_only=True) == []
    assert ms.update_note(note['id'], project_id=2, **changes) is None
    assert ms.update_note(note['id'], project_id=1)['auto'] == 1
    updated = ms.update_note(note['id'], project_id=1, **changes)
    assert updated['auto'] == 0
    assert ms.project_note_items(project_id=1, explicit_only=True)[0]['id'] == note['id']
