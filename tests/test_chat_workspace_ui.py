import asyncio

import pytest

from sovushka.components import chat_workspace as module


@pytest.mark.asyncio
async def test_open_project_restores_last_session_without_choosing_sources(monkeypatch):
    opened = []
    record = {"session_id": "last", "project_id": 7, "scope": {"dataset_ids": ["chosen"]}}

    async def get(path):
        assert path == "/api/workspace/sessions?project_id=7"
        return [record]

    async def open_record(value):
        opened.append(value)
        return True

    monkeypatch.setattr(module, "api_get", get)
    workspace = module.ChatWorkspace(on_open=open_record, get_session_id=lambda: "old", is_busy=lambda: False)
    await workspace.open_project(7)
    assert opened == [record]
    assert workspace.active == record


@pytest.mark.asyncio
async def test_new_chat_keeps_owner_and_uses_server_defaults(monkeypatch):
    posted = []
    record = {"session_id": "new", "project_id": 7, "scope": {"dataset_ids": ["default"]}}

    async def post(path, data):
        posted.append((path, data))
        return record

    async def open_record(value):
        return True

    monkeypatch.setattr(module, "api_post", post)
    workspace = module.ChatWorkspace(on_open=open_record, get_session_id=lambda: "old", is_busy=lambda: False)
    workspace.active = {"project_id": 7, "session_id": "old"}
    await workspace.new_session()
    assert posted == [("/api/workspace/sessions", {"project_id": 7})]
    assert workspace.active == record


@pytest.mark.asyncio
async def test_failed_session_open_does_not_switch_owner():
    async def open_record(value):
        return False

    workspace = module.ChatWorkspace(on_open=open_record, get_session_id=lambda: "old", is_busy=lambda: False)
    workspace.active = {"session_id": "old", "project_id": 1}
    assert await workspace.activate({"session_id": "new", "project_id": 2}) is False
    assert workspace.active["project_id"] == 1


def test_chat_wiring_persists_before_model_send_and_clears_transient_state():
    from pathlib import Path
    source = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")
    assert "await workspace.persist(" in source
    assert 'payload["project_id"] = workspace.active.get("project_id")' in source
    activation = source.split("async def _activate_workspace_session", 1)[1].split("async def ", 1)[0]
    assert "_clear_file_artifacts()" in activation
    assert "artifact_panel.clear()" in activation
    assert 'detail_dataset.set_value("(все датасеты)")' in activation
    assert "reranker_checkbox.set_value(False)" in activation
    assert 'scope_state.update(record.get("scope")' in activation


@pytest.mark.asyncio
async def test_navigation_blocks_second_open_and_send_until_owner_is_committed():
    started, finish = asyncio.Event(), asyncio.Event()

    async def open_record(record):
        started.set()
        await finish.wait()
        return True

    workspace = module.ChatWorkspace(on_open=open_record, get_session_id=lambda: "old", is_busy=lambda: False)
    task = asyncio.create_task(workspace.activate({"session_id": "a", "project_id": 1}))
    await started.wait()
    try:
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(workspace.activate({"session_id": "b", "project_id": 2}), timeout=0.1)
        with pytest.raises(RuntimeError):
            await workspace.persist(scope={}, role="agent", title="question")
    finally:
        finish.set()
        await task
    assert workspace.active["session_id"] == "a"


def test_workspace_uses_brand_tokens_for_actions_and_checkboxes():
    from sovushka.uikit import UIKIT_CSS
    assert '.sov-ui-checkbox .q-checkbox__inner--truthy' in UIKIT_CSS
    assert 'color: var(--accent) !important;' in UIKIT_CSS
    assert '--q-primary: var(--accent) !important;' in UIKIT_CSS


def test_source_and_response_dialogs_reuse_approved_memory_controls():
    from pathlib import Path
    source = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")
    assert 'panel(variant="raised", classes="sov-ui-dialog")' in source
    assert 'min-width:620px' not in source
    assert 'section_heading("Настройки ответа")' in source

@pytest.mark.asyncio
async def test_created_project_is_opened_and_navigation_notified(monkeypatch):
    events = []
    async def post(path, data):
        if path == '/api/projects':
            assert data == {'name': 'School'}
            return {'id': 9, 'name': 'School'}
        return {'session_id': 'new-project-chat', 'project_id': 9}
    async def get(path):
        return {'sessions': []}
    async def opened(record):
        events.append(('opened',record['project_id']))
        return True
    async def changed():
        events.append(('changed',workspace.active['project_id']))
    monkeypatch.setattr(module,'api_post',post)
    monkeypatch.setattr(module,'api_get',get)
    workspace = module.ChatWorkspace(on_open=opened,get_session_id=lambda:'old',is_busy=lambda:False,on_change=changed)
    await workspace.create_project(' School ')
    assert workspace.project_names[9] == 'School'
    assert events == [('opened',9),('changed',9)]

@pytest.mark.asyncio
async def test_project_creation_does_not_write_when_busy(monkeypatch):
    async def forbidden(*args,**kwargs):
        pytest.fail('Busy navigation must not create a project')
    monkeypatch.setattr(module,'api_post',forbidden)
    workspace = module.ChatWorkspace(on_open=forbidden,get_session_id=lambda:'old',is_busy=lambda:True)
    with pytest.raises(RuntimeError):
        await workspace.create_project('School')


def test_chat_redesign_keeps_projects_and_configuration_visible():
    from pathlib import Path
    source = Path('sovushka/pages/chat.py').read_text(encoding='utf-8')
    assert 'ChatProjectNavigation' in source
    assert 'sov-chat-workspace' in source
    navigation = Path('sovushka/components/chat_project_navigation.py').read_text(encoding='utf-8')
    assert 'Создать проект' in navigation
    assert 'Конфигурация' in navigation
    assert '/les/classic' in navigation
    assert 'Студия' not in navigation and 'CAD' not in navigation
@pytest.mark.parametrize('destination', ['history', 'data'])
def test_mobile_navigation_closes_before_opening_another_surface(destination):
    from types import SimpleNamespace
    from sovushka.components.chat_project_navigation import ChatProjectNavigation
    events = []
    nav = ChatProjectNavigation(None, on_new=None, on_history=lambda:events.append('history'),
                                on_data=lambda:events.append('data'))
    nav.sidebar = SimpleNamespace(classes=lambda **kwargs:events.append('closed'))
    nav.mobile_open = True
    getattr(nav, 'open_' + destination)()
    assert events == ['closed', destination]
    assert not nav.mobile_open