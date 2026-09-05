import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from proxy.routers import workspace
from proxy.services import chat_session_service as service


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'rag_meta_db_path', lambda: str(tmp_path / 'meta.sqlite'))
    app = FastAPI()
    app.include_router(workspace.router)
    app.dependency_overrides[workspace.require_user] = lambda: {'username': 'tester'}
    with TestClient(app) as client:
        yield client


def test_session_api_roundtrip_and_immutable_ownership(client):
    response = client.post('/api/workspace/sessions', json={'title': 'One'})
    assert response.status_code == 200
    sid = response.json()['session_id']
    assert client.get('/api/workspace/sessions').json()['sessions'][0]['session_id'] == sid
    assert client.patch(f'/api/workspace/sessions/{sid}', json={'title': 'Two'}).json()['title'] == 'Two'
    assert client.get(f'/api/workspace/sessions/{sid}').json()['title'] == 'Two'
    assert client.patch(f'/api/workspace/sessions/{sid}', json={'project_id': 1}).status_code == 422
    assert client.post('/api/workspace/sessions', json={'session_id': sid}).status_code == 409
    assert client.post('/api/workspace/sessions', json={'project_id': 999}).status_code == 404
    assert client.get('/api/workspace/sessions/missing').status_code == 404
    assert client.post('/api/workspace/sessions', json={'session_id': '../bad'}).status_code == 422


def test_all_session_routes_require_authenticated_user(client):
    from fastapi import HTTPException

    def deny():
        raise HTTPException(401, 'Unauthorized')

    client.app.dependency_overrides[workspace.require_user] = deny
    assert client.get('/api/workspace/sessions').status_code == 401
    assert client.get('/api/workspace/sessions/test').status_code == 401
    assert client.post('/api/workspace/sessions', json={}).status_code == 401
    assert client.patch('/api/workspace/sessions/test', json={}).status_code == 401
