import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from proxy.security import require_user
from proxy.services import memory_service, project_service


@pytest.fixture
def client(tmp_path, monkeypatch):
    from proxy.routers import workspace_memory
    path = str(tmp_path / 'meta.db')
    for service in (memory_service, project_service):
        monkeypatch.setattr(service, 'rag_meta_db_path', lambda: path)
    project_service.create_project('One')
    project_service.create_project('Two')
    app = FastAPI()
    app.include_router(workspace_memory.router)
    app.dependency_overrides[require_user] = lambda: {'role': 'user'}
    with TestClient(app) as client:
        yield client


BASE = '/api/workspace/memory'


def test_explicit_crud_and_scope(client):
    global_note = client.post(BASE, json={'text': 'global'}).json()
    response = client.post(BASE, json={'text': '  project preference  ', 'project_id': 1})
    assert response.status_code == 200
    note = response.json()
    assert note['text'] == 'project preference'
    assert [n['id'] for n in client.get(BASE).json()['notes']] == [global_note['id']]
    assert [n['id'] for n in client.get(BASE, params={'project_id': 1}).json()['notes']] == [note['id']]
    url = f"{BASE}/{note['id']}"
    assert client.patch(url, json={'project_id': 2, 'enabled': False}).status_code == 404
    assert client.delete(url, params={'project_id': 2}).status_code == 404
    assert client.patch(url, json={'project_id': 1, 'text': 'edited', 'enabled': False}).json()['enabled'] == 0
    assert client.get(BASE, params={'project_id': 1}).json()['notes'][0]['text'] == 'edited'
    assert client.delete(url, params={'project_id': 1}).json() == {'deleted': True}


@pytest.mark.parametrize('body', [{'text': ' '}, {'text': 'x' * 2001}, {'text': 'ok', 'project_id': -1}])
def test_validation(client, body):
    assert client.post(BASE, json=body).status_code == 422


def test_unknown_project_and_required_patch_scope(client):
    assert client.post(BASE, json={'text': 'ok', 'project_id': 99}).status_code == 404
    note = client.post(BASE, json={'text': 'ok'}).json()
    assert client.patch(f"{BASE}/{note['id']}", json={'text': 'edit'}).status_code == 422
    assert client.delete(f"{BASE}/{note['id']}").status_code == 422


def test_requires_user(client):
    assert require_user in client.app.dependency_overrides
    for route in client.app.routes:
        if getattr(route, 'path', '').startswith(BASE):
            assert require_user in [d.call for d in route.dependant.dependencies]


def test_source_session_must_match_scope(client, monkeypatch):
    from proxy.services import chat_session_service
    monkeypatch.setattr(chat_session_service, 'rag_meta_db_path', memory_service.rag_meta_db_path)
    session = chat_session_service.create_session(project_id=1)
    source = session['session_id']
    assert client.post(BASE, json={'text': 'source note', 'project_id': 2, 'source_session_id': source}).status_code == 422
    assert client.post(BASE, json={'text': 'source note', 'source_session_id': source}).status_code == 422
    assert client.post(BASE, json={'text': 'source note', 'source_session_id': 'missing'}).status_code == 422
    response = client.post(BASE, json={'text': 'source note', 'project_id': 1, 'source_session_id': source})
    assert response.status_code == 200
    assert response.json()['source_session_id'] == source
